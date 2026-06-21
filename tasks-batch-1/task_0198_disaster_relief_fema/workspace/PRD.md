# Disaster Relief & FEMA Case Management API — Product Requirements Document

## 1. Introduction

When a federally-declared disaster strikes, the Individuals and Households Program (IHP) is the channel through which affected families receive financial help for repairs, lost personal property, and temporary housing. This API is the system of record for that program. It carries a household from the moment it registers against a disaster declaration, through field inspection of the damage, through an eligibility determination and award calculation, and finally through the disbursement of funds — while continuously guarding against the single most consequential failure mode in federal relief: paying a household money it has already received from another source.

The domain is unforgiving in two directions at once. On one side, awards must be generous enough and fast enough to matter to people who have lost their homes; on the other, every dollar is a federal obligation subject to audit, duplication-of-benefits (DOB) law, and recoupment if an overpayment is later discovered. Because benefits from insurers, the Small Business Administration (SBA), charities, and other federal programs frequently arrive *after* an award has already been disbursed, the system must treat award figures as living quantities that can be recomputed and clawed back long after the case looked settled. A household may also contest a determination through an appeal, and the caseworker who decided the original award is barred from deciding that appeal.

This document specifies the entities, state machines, award arithmetic, validation precedence, and access-control rules that together make those guarantees enforceable. It is written for the engineers who will implement the service and is the sole authority on its behavior.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are served under the `/disaster-relief` mount.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_MISSING_OR_INVALID_AUTH`. When the headers are well-formed but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly three roles: `ProgramAdmin`, `Inspector`, and `Caseworker`.

The `ProgramAdmin` is the operational administrator. This role sets up disaster declarations, opens and closes registration, imports duplication-of-benefits records, voids disbursements, establishes and recovers and waives recoupment debts, and drives the test clock. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.

The `Inspector` is the field inspector. This role schedules and conducts damage assessments but cannot determine eligibility or compute awards. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector`; ownership checks on any resource that references an `Inspector` compare the resource's `inspector_id` to `X-User-ID`.

The `Caseworker` is the eligibility caseworker. This role verifies assessments, opens and approves and denies IHP cases, files and decides appeals (subject to segregation of duties), refers cases to the SBA, records duplication-of-benefits sources, and disburses funds. When `X-User-Role` is `Caseworker`, `X-User-ID` is the `id` of the acting `Caseworker`; ownership and segregation-of-duties checks on any resource that references a `Caseworker` compare the resource's caseworker foreign-key field (for example `determined_by_caseworker_id` or `decided_by_caseworker_id`) to `X-User-ID`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Resource Identity

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix. Each also carries a `created_at` timestamp, expressed in ISO 8601 UTC with three fractional digits, recording when the resource was first created.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation of the resource, and `version` begins at its initial value and increments by one with each mutation. These two fields are present on `DisasterDeclaration`, `Inspector`, `Caseworker`, `Applicant`, `DamageAssessment`, `IhpCase`, `AwardLineItem`, `DobRecord`, `Appeal`, `SbaReferral`, `Disbursement`, `RentalAssistancePeriod`, and `Recoupment` — every entity in this system carries the full set of common fields.

When a derived figure on a resource changes as a consequence of some workflow — for instance when an `IhpCase`'s computed award totals are recomputed — that recomputation is itself a mutation: it refreshes the resource's `updated_at` and increments its `version`. The exact version-increment points on `IhpCase` are enumerated in the workflow narratives of §3, because the `version` is also the basis of optimistic concurrency control (§2.7) and the precise count matters.

### 2.5. Nested Resource Retrieval and Referential Validation

All business resources are peer collections under `/disaster-relief`; the URL hierarchy never nests one business resource inside another. A resource is addressed either by its collection or by its collection plus its `{id}`.

Even though paths are flat, requests routinely name other resources through foreign-key body fields. Existence is validated left to right: any resource `id` appearing in the path is checked first, then any required foreign-key field in the request body, in declaration order. The first identifier that does not resolve to an existing resource causes the request to be rejected with the not-found error specific to that resource type — `ERR_DECLARATION_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_CASEWORKER_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_DOB_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, or `ERR_RECOUPMENT_NOT_FOUND` — each carrying HTTP 404.

List endpoints support reverse-reachability filters by foreign key. Applicants may be filtered by `declaration_id`; assessments by `applicant_id` or `inspector_id`; IHP cases by `applicant_id`, `assessment_id`, or `determined_by_caseworker_id`; award line items by `ihp_case_id`; DOB records by `applicant_id`; appeals by `ihp_case_id` or `decided_by_caseworker_id`; SBA referrals by `ihp_case_id`; disbursements by `ihp_case_id` or `line_item_id`; recoupments by `ihp_case_id`; and rental-assistance periods by `ihp_case_id` or `applicant_id`. Several list endpoints also accept a `status` filter (and, where noted in §4, category/type filters such as `category`, `li_status`, `dob_status`, `source_type`, `disb_status`, and `origin`).

### 2.6. Monetary Values and Computational Precision

All monetary amounts in this system are stored and transmitted as integer cents. There is no fractional-cent arithmetic and there are no floating-point monetary fields. The award formulas of §3 operate entirely on integer cents and integer month counts; no rounding is performed inside the eligibility formula because all of its inputs are already integer cents.

The one place rounding-style arithmetic does occur is the proportional reduction applied when a household's gross eligibility exceeds the per-household cap. There, each component is reduced by taking the floor of its scaled value (discarding any fractional cent), and the pennies lost to flooring are redistributed deterministically. The exact procedure, including the fixed order in which components are processed and where the leftover pennies land, is specified in §3.6. The phrase "round down" or "take the floor" in this document always means: discard the fractional part toward zero, keeping the integer-cent value.

### 2.7. Optimistic Concurrency Control on Case Ledgers

Two write operations require the client to prove it is acting on a current view of an `IhpCase`'s ledger, because both can silently over-commit funds if executed against a stale view. Both carry the integer field `expected_ihp_case_version`, which is the `version` of the target `IhpCase` that the client last observed.

The first is creating a `Disbursement`. The create request must carry `expected_ihp_case_version` matching the target case's current `version`. If another writer has advanced the case's `version` since the disbursing caseworker last read it — for example by recording an earlier disbursement that already consumed part of the remaining obligation — the create is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), preventing the caseworker from over-disbursing against a ledger view that no longer holds.

The second is creating an `Appeal`. The create request must likewise carry `expected_ihp_case_version` matching the case's current `version`. If the case's decision or award has been re-evaluated since the appellant last read it, advancing the `version`, the appeal is filed against a decision that no longer stands and is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412).

`expected_ihp_case_version` is a required field on both of these create operations; it is not optional and there is no "skip the check" path. No other endpoint in this system accepts a version field.

### 2.8. Segregation of Duties on Appeals

Eligibility integrity depends on independent review. The `Caseworker` who renders the original eligibility determination on an `IhpCase` is recorded in `determined_by_caseworker_id`, set when the case is approved or denied. That same caseworker is barred from deciding any appeal on that same case. When an appeal is decided, the deciding caseworker is recorded in the appeal's `decided_by_caseworker_id`, and if that caseworker's `id` equals the case's `determined_by_caseworker_id`, the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Inspector and caseworker operations are otherwise disjoint: an inspector conducts inspections and a caseworker determines eligibility, and neither can perform the other's exclusive actions.

### 2.9. Derived Ledger Fields and the Obligation Invariant

Several fields on the case and on the applicant are derived — never set directly by a client, always reconciled by the server as a consequence of some event. On the `Applicant`, `total_dob_cents` is the running sum of duplication-of-benefits amounts recorded against that household (the precise rule appears in §3.5). On the `IhpCase`, the chain of derived figures is `gross_eligible_cents`, `capped_eligible_cents`, `dob_offset_cents`, `net_eligible_cents`, `total_approved_cents`, `disbursed_total_cents`, and `remaining_obligation_cents`. Each `AwardLineItem` likewise carries the derived `gross_amount_cents` and `approved_amount_cents`.

Two invariants hold across these figures at all times. First, the remaining obligation is always the approved total minus what has already been paid: `disbursed_total_cents` plus `remaining_obligation_cents` always equals `total_approved_cents`. Second, the duplication offset and net entitlement always satisfy `net_eligible_cents` equal to the larger of zero and `capped_eligible_cents` minus `dob_offset_cents`. Every operation that touches money — approval, disbursement, void, DOB recording or reversal, SBA approval, appeal grant — recomputes the affected derived fields synchronously inside the triggering request before responding, so these invariants are never observably broken. All such cascades complete within the request that triggers them; there is no deferred or background reconciliation.

### 2.10. The Logical Clock

Because eligibility depends on dates — a registration deadline, an incident period, the moment a duplicative benefit was received — the server maintains a logical "current" UTC instant that test harnesses can pin. An administrative test-driving capability accepts a single `to_iso8601` instant and fixes the server's notion of the current UTC time to it for all subsequent requests. Registration-deadline checks, incident-period checks, and the at-award duplication filter (which compares a benefit's `received_at` against the case's approval time) all read this logical clock.

## 3. Business Logic & Workflows

### 3.1. Declarations, Inspectors, and Caseworkers: the Program Setup

Everything begins with a `DisasterDeclaration`, created by a `ProgramAdmin`. A declaration is described by a `title` such as "DR-4827 Severe Storms", an incident window bounded by `incident_start` and `incident_end` (both ISO 8601 UTC, with `incident_end` required to be at or after `incident_start`), a per-household financial-assistance cap `ihp_max_grant_cents`, and a `registration_deadline` after which no household may register. A declaration is born `OPEN`. A `ProgramAdmin` later closes registration, moving it `OPEN → REGISTRATION_CLOSED`; this requires the declaration to be `OPEN` (otherwise `ERR_DECLARATION_NOT_OPEN`) and thereafter blocks creation of any new applicant against it. From `REGISTRATION_CLOSED` the same role finally closes the declaration outright, moving it `REGISTRATION_CLOSED → CLOSED`; this requires the declaration to be in `REGISTRATION_CLOSED` (otherwise `ERR_DECLARATION_NOT_REGISTRATION_CLOSED`) and requires that no `IhpCase` under the declaration is in `DISBURSING` (otherwise `ERR_OPEN_DISBURSING_CASES`). Once a declaration is `CLOSED`, disbursement creation against its cases is blocked. The declaration's `status` is the enumeration `OPEN`, `REGISTRATION_CLOSED`, `CLOSED`.

A `ProgramAdmin` also provisions the program's staff. An `Inspector` is created with a `full_name` and a `badge_number` that must be unique across all inspectors, plus an optional `travel_buffer_minutes` that defaults to 30 and expresses the minimum gap the inspector needs between two appointments. An inspector's `status` is `ACTIVE` or `SUSPENDED` and begins `ACTIVE`. A `Caseworker` is created with a `full_name`, an `employee_id` unique across all caseworkers, and an optional `can_approve_awards` boolean that defaults to true and records whether this caseworker may approve awards rather than merely recommend them. A caseworker's `status` is likewise `ACTIVE` or `SUSPENDED`, beginning `ACTIVE`. Both inspector and caseworker records are the entity-backed identities behind the `Inspector` and `Caseworker` roles described in §2.1.

### 3.2. Household Intake and Inspection

A household enters the program as an `Applicant`, registered by a `Caseworker` or `ProgramAdmin` against a specific declaration. Registration captures the `declaration_id` the household is registering under, the `household_name` of the head of household, the `household_size` (which must be at least 1), the self-reported `annual_income_cents` (which must be at least 0 and later feeds the SBA income test), the `damage_date` on which the disaster damage occurred, and three self-reported loss figures that drive the provisional award: `reported_repair_cost_cents`, `reported_personal_property_cents`, and `reported_rental_months` (each at least 0). A newly registered applicant starts in `REGISTERED` with `total_dob_cents` initialized to 0.

Registration is gated on time and on the incident window. The declaration must be `OPEN` and the request must arrive on or before the declaration's `registration_deadline`; if the declaration is not `OPEN` or the deadline has passed, registration is rejected with `ERR_REGISTRATION_CLOSED`. Separately, the household's `damage_date` must fall within the inclusive incident period — that is, on or after `incident_start` and on or before `incident_end`; a damage date outside that window is rejected with `ERR_DAMAGE_DATE_OUT_OF_PERIOD`. An applicant's `status` walks the enumeration `REGISTERED`, `INSPECTION_SCHEDULED`, `INSPECTED`, `ELIGIBILITY_PENDING`, `ELIGIBLE`, `INELIGIBLE`, `WITHDRAWN`.

Scheduling an inspection creates a `DamageAssessment` for the applicant and advances the applicant `REGISTERED → INSPECTION_SCHEDULED`; this requires the applicant to be `REGISTERED` (otherwise `ERR_APPLICANT_NOT_REGISTERED`). The new assessment names the `applicant_id` it covers, the `inspector_id` conducting it, and an appointment window bounded by `scheduled_start` and `scheduled_end` (with `scheduled_end` required to be strictly after `scheduled_start`). The assessment is born `SCHEDULED`; its `status` ranges over `SCHEDULED`, `INSPECTED`, `VERIFIED`, `CANCELLED`.

Before the slot is accepted, the inspector's calendar is checked for collisions. A new assessment must not collide with any other non-terminal appointment — one that is `SCHEDULED` or `INSPECTED` — of the *same* inspector. The geometry is a closed interval widened by the inspector's `travel_buffer_minutes` on both sides: the two appointments collide when the new appointment's `scheduled_start` is at or before the other appointment's `scheduled_end` plus the buffer, and simultaneously the other appointment's `scheduled_start` is at or before the new appointment's `scheduled_end` plus the buffer. Because the buffer is added to both ends and the comparison is inclusive, appointments that merely touch — or that fall within the buffer of one another — do collide. A collision is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`.

A household that has not yet progressed can be withdrawn by a `Caseworker` or `ProgramAdmin`, moving the applicant to `WITHDRAWN`. Withdrawal is permitted only while the applicant is `REGISTERED` or `INSPECTION_SCHEDULED` (otherwise `ERR_APPLICANT_NOT_WITHDRAWABLE`), and as a side effect any `SCHEDULED` `DamageAssessment` belonging to that applicant is transitioned to `CANCELLED`, which frees the inspector's calendar slot.

When the inspector visits the home, recording the inspection advances the assessment `SCHEDULED → INSPECTED` and the applicant `INSPECTION_SCHEDULED → INSPECTED`. This is an `Inspector`-only action and requires the assessment to be `SCHEDULED` (otherwise `ERR_ASSESSMENT_NOT_SCHEDULED`). The inspector must supply all four inspection results: `habitability` (either `HABITABLE`, meaning minor damage and repair only, or `UNINHABITABLE`, which unlocks rental and replacement assistance), and the inspector-verified figures `verified_repair_cost_cents`, `verified_personal_property_cents`, and `verified_rental_months`. If any of these required inspection fields is absent, the request is rejected with `ERR_MISSING_REQUIRED_FIELD`. These verified amounts are recorded on the assessment and become the basis of the final award.

A `Caseworker` then verifies the inspected assessment, advancing it `INSPECTED → VERIFIED`; this requires the assessment to be `INSPECTED` (otherwise `ERR_ASSESSMENT_NOT_INSPECTED`). Only a `VERIFIED` assessment may seed an IHP case. Alternatively, a `SCHEDULED` assessment may be cancelled by an `Inspector` or `ProgramAdmin`, moving it `SCHEDULED → CANCELLED` (requires `SCHEDULED`, otherwise `ERR_ASSESSMENT_NOT_SCHEDULED`), which frees the inspector's calendar slot. The terminal assessment states are `VERIFIED` and `CANCELLED`.

### 3.3. Opening a Case and the Provisional Award

Once an applicant is `INSPECTED` and the inspection has been `VERIFIED`, a `Caseworker` opens an `IhpCase`. The create request supplies the `applicant_id`, the `assessment_id` of the verified assessment the case is built from, and the locality's `monthly_fmr_cents` (Fair Market Rent per month in cents, the unit rate for rental assistance, at least 0). The applicant must be `INSPECTED` (otherwise `ERR_APPLICANT_NOT_INSPECTED`) and the referenced assessment must be `VERIFIED` (otherwise `ERR_ASSESSMENT_NOT_VERIFIED`). On creation the applicant advances `INSPECTED → ELIGIBILITY_PENDING`.

A case is created in `DRAFT` and immediately, within the same request, advanced to `ELIGIBILITY_PENDING`. During that advance the system computes a **provisional** award from the household's *self-reported* figures and lays down one `AwardLineItem` per applicable category in `PENDING`. The case's `status` enumeration is `DRAFT`, `ELIGIBILITY_PENDING`, `AWARD_APPROVED`, `DENIED`, `DISBURSING`, `UNDER_APPEAL`, `CLOSED`, with `CLOSED` terminal.

The eligibility computation, used here in its provisional variant and later in its final variant, works component by component. The repair component is the smaller of the applicable repair cost and a per-component repair cap of $41,500 (4,150,000 cents). The personal-property component is the smaller of the applicable personal-property loss and a per-component cap of $41,500 (4,150,000 cents). The remaining two components depend on habitability. If the home is `HABITABLE`, both the rental-assistance component and the replacement component are zero. If the home is `UNINHABITABLE`, the rental-assistance component is the monthly Fair Market Rent multiplied by the number of rental months, and the replacement component is the smaller of the applicable repair cost and a replacement cap of $41,500 (4,150,000 cents), but only when the applicable repair cost exceeds the $41,500 repair cap; otherwise the replacement component is zero. The gross eligible amount is the sum of these four components: repair assistance plus personal property plus rental assistance plus replacement. All amounts are integer cents and integer months, and no rounding occurs in this sum.

The provisional variant feeds this formula from the applicant's self-reported numbers — `reported_repair_cost_cents` as the repair cost, `reported_personal_property_cents` as the personal-property loss, and `reported_rental_months` as the rental months. Habitability, however, is an inspector finding, so the provisional pass at case creation uses the verified assessment's recorded habitability. The resulting figure populates the case's `gross_eligible_cents`. At this provisional stage the cap and the duplication offset have not yet been applied; those belong to approval.

### 3.4. Determination: Approval and Denial

A `Caseworker` renders the determination on a pending case, either approving it or denying it. Both actions require the case to be `ELIGIBILITY_PENDING` (otherwise `ERR_CASE_NOT_PENDING`), and both record the acting caseworker in `determined_by_caseworker_id` — the field that later enforces segregation of duties on appeal — and increment the case's `version` by one.

Approval advances the case `ELIGIBILITY_PENDING → AWARD_APPROVED` and recomputes the award in its **final** variant. The final variant runs the same component formula as §3.3 but draws its repair cost, personal-property loss, and rental months from the inspector-verified figures `verified_repair_cost_cents`, `verified_personal_property_cents`, and `verified_rental_months` rather than the self-reported ones; the result refreshes `gross_eligible_cents`. The per-household cap is then applied: `capped_eligible_cents` is the smaller of `gross_eligible_cents` and the declaration's `ihp_max_grant_cents`. The duplication-of-benefits offset is computed in its at-award variant (see §3.5) into `dob_offset_cents`, and the net entitlement `net_eligible_cents` is the larger of zero and `capped_eligible_cents` minus `dob_offset_cents`. Approval requires that the final `net_eligible_cents` be strictly greater than zero; if it would be zero or negative, the case must be denied instead, and an approval attempt is rejected with `ERR_NO_ELIGIBLE_AMOUNT`. The damage date having fallen within the incident period is a condition already validated at case creation. On a successful approval, each `AwardLineItem` receives its `approved_amount_cents` through the cap-and-offset waterfall of §3.6, the line items advance to `APPROVED`, `total_approved_cents` is reconciled as the sum of approved line amounts, and the applicant advances `ELIGIBILITY_PENDING → ELIGIBLE`.

Denial advances the case `ELIGIBILITY_PENDING → DENIED`. All of the case's award line items are transitioned to `VOIDED`, `total_approved_cents` is reset to 0, and the applicant advances `ELIGIBILITY_PENDING → INELIGIBLE`. The applicant transitions to `ELIGIBLE` and `INELIGIBLE` are system-driven consequences of the case reaching `AWARD_APPROVED` (with a positive net entitlement) and `DENIED` respectively; they are not separately invokable.

### 3.5. Duplication of Benefits

A `DobRecord` captures a benefit the household has received from somewhere other than IHP, so that the program does not pay twice for the same loss. A `ProgramAdmin` or `Caseworker` records one with the `applicant_id`, the `source_type` (one of `INSURANCE`, `SBA_LOAN`, `CHARITY`, `OTHER_FEDERAL`), the `amount_cents` (at least 0), and `received_at`, the instant the benefit was received or settled, which determines whether the benefit counts as known at award time or as a late arrival. A DOB record's `dob_status` is `RECORDED` or `REVERSED`, beginning `RECORDED`; only `RECORDED` rows count toward the household's duplication totals.

The applicant's `total_dob_cents` is reconciled on every DOB mutation as the sum of `amount_cents` over that applicant's DOB records whose `dob_status` is `RECORDED`. The duplication offset applied to a case comes in two variants. The **at-award** variant, computed when a case is approved, sums the `amount_cents` of the applicant's `RECORDED` DOB records whose `received_at` is at or before the case's approval time — that is, only duplications already known at award time. The **at-recoupment** variant, computed after an SBA approval, after a late DOB record is added, or after a DOB reversal, sums the `amount_cents` of *all* of the applicant's `RECORDED` DOB records regardless of when they were received — so a benefit whose `received_at` is later than the case's approval time enters the offset only in the at-recoupment variant, and that difference is precisely what can drive a recoupment. In both variants the computed sum becomes `dob_offset_cents`, and `net_eligible_cents` is reset to the larger of zero and `capped_eligible_cents` minus `dob_offset_cents`.

Recording a DOB has cascading effect when the household already has a live case. After `total_dob_cents` is recomputed, if the applicant's case is `AWARD_APPROVED` or `DISBURSING`, the case's `dob_offset_cents` and `net_eligible_cents` are recomputed using the at-recoupment variant; and if at that point the case's `disbursed_total_cents` exceeds the freshly recomputed `net_eligible_cents`, a `LATE_DOB` `Recoupment` is established for the overpayment (see §3.9).

A `ProgramAdmin` may reverse a `RECORDED` DOB record, moving it `RECORDED → REVERSED`; this requires the record to be `RECORDED` (otherwise `ERR_DOB_NOT_RECORDED`). Reversal subtracts that record's `amount_cents` from the applicant's `total_dob_cents` — a compensating action that keeps the total honest — and, when the linked case is `AWARD_APPROVED` or `DISBURSING`, recomputes the case's `dob_offset_cents` and `net_eligible_cents`.

### 3.6. The Cap-and-Offset Waterfall

When a case is approved (and again when an appeal is granted), each `AwardLineItem`'s `approved_amount_cents` is set by a two-step waterfall that runs over the line items in one fixed category order: `RENTAL_ASSISTANCE`, then `REPAIR_ASSISTANCE`, then `PERSONAL_PROPERTY`, then `REPLACEMENT`. Each line item's `category` is one of those four values, its pre-cap pre-offset eligibility lives in `gross_amount_cents`, and its `li_status` ranges over `PENDING`, `APPROVED`, `DISBURSED`, `VOIDED`.

The first step applies the per-household cap proportionally, but only when the case's `gross_eligible_cents` exceeds the declaration's `ihp_max_grant_cents`. In that case a scale factor equal to `ihp_max_grant_cents` divided by `gross_eligible_cents` is formed as an exact rational and not yet rounded. Each line's capped amount is then the floor of its `gross_amount_cents` multiplied by that scale factor — every line is floored independently. Because flooring discards fractional cents, the sum of the floored lines will generally fall short of `ihp_max_grant_cents`; the shortfall, computed as `ihp_max_grant_cents` minus the sum of the floored line amounts, is assigned in full to the last non-zero line in the fixed category order, so the capped lines sum back exactly to the cap. When `gross_eligible_cents` does not exceed the cap, each line's capped amount is simply its own `gross_amount_cents`, with no scaling.

The second step subtracts the duplication offset across the capped lines, again in the same fixed category order. Starting with a remaining offset equal to `dob_offset_cents`, the system walks the lines in order; for each line it takes the smaller of that line's capped amount and the remaining offset, sets the line's `approved_amount_cents` to its capped amount minus that taken amount, and reduces the remaining offset by the amount taken. All values stay integer cents throughout. The case's `total_approved_cents` is the sum of `approved_amount_cents` over the `APPROVED` lines. The ordering is pinned and consequential: the cap-proration floor happens per line *before* any DOB subtraction, because flooring first and subtracting second yields different per-line cents than the reverse order would.

### 3.7. SBA Referral and Its Cascade

When a household's verified losses or income suggest it could carry a disaster loan, a `Caseworker` refers the case to the SBA by creating an `SbaReferral` with the `ihp_case_id`. The referral is eligibility-gated: it is permitted only if the applicant's `annual_income_cents` is at or below the income ceiling of $75,000 (7,500,000 cents), or the verified total loss is strictly greater than the loss threshold of $30,000 (3,000,000 cents). The verified total loss is the sum of the assessment's `verified_repair_cost_cents` and `verified_personal_property_cents`. The boundaries are exact: an income exactly equal to the $75,000 ceiling qualifies (the comparison is at-or-below), while a verified loss exactly equal to the $30,000 threshold does *not* qualify (the comparison is strictly greater). When neither condition holds — income above the ceiling and verified loss at or below the threshold — the referral is rejected with `ERR_SBA_NOT_ELIGIBLE`. On a successful create the verified total loss is snapshotted into `referred_loss_cents` and the referral is born `REFERRED`. The referral's `status` is `REFERRED`, `SBA_APPROVED`, or `SBA_DECLINED`.

A `Caseworker` or `ProgramAdmin` later records the SBA's decision, which requires the referral to be `REFERRED` (otherwise `ERR_REFERRAL_NOT_OPEN`). The `outcome` must be either `APPROVED` or `DECLINED`; if it is anything else, or if it is `APPROVED` without an `sba_loan_amount_cents`, the request is rejected with `ERR_INVALID_SBA_OUTCOME`. A declined outcome advances the referral `REFERRED → SBA_DECLINED` and has no further effect — no DOB record is created and the household remains eligible for its full IHP award; this is the divergent, no-cascade branch.

An approved outcome advances the referral `REFERRED → SBA_APPROVED` and triggers a three-hop cascade. First, an `SBA_LOAN` `DobRecord` is created on the applicant for the `sba_loan_amount_cents` SBA approved. Second, the applicant's `total_dob_cents` is recomputed and, because an SBA loan is by nature a late-arriving duplication, the case's `dob_offset_cents` and `net_eligible_cents` are recomputed in the at-recoupment variant. Third, if the case's `disbursed_total_cents` now exceeds the freshly recomputed `net_eligible_cents`, a `LATE_DOB` `Recoupment` is established for the overpayment.

### 3.8. Disbursing Funds

A `Caseworker` disburses money against an approved line item. A `Disbursement` names the `ihp_case_id`, the `line_item_id` being paid, the `expected_ihp_case_version` for the optimistic-concurrency check of §2.7, and the `amount_cents` to pay (at least 1). Its `disb_status` is `PAID` or `VOIDED`, beginning `PAID`.

The first disbursement on a case requires the case to be `AWARD_APPROVED` (otherwise `ERR_CASE_NOT_APPROVED`) and advances it `AWARD_APPROVED → DISBURSING`. Subsequent disbursements require the case to already be `DISBURSING` (otherwise `ERR_CASE_NOT_DISBURSING`). In every case the declaration must not be `CLOSED` (otherwise `ERR_DECLARATION_CLOSED`). The named `line_item_id` must belong to the same case as `ihp_case_id` and must be in `APPROVED` status; a line item that is not approved or that belongs to a different case is rejected with `ERR_LINE_ITEM_NOT_APPROVED`. The amount must not exceed the case's `remaining_obligation_cents`; an over-draw is rejected with `ERR_DISBURSEMENT_EXCEEDS_OBLIGATION` (HTTP 402). On success the disbursement is recorded `PAID`, the case's `disbursed_total_cents` increases by the paid amount, `remaining_obligation_cents` is recomputed, and the case's `version` increments by one.

A `ProgramAdmin` may void a `PAID` disbursement, moving it `PAID → VOIDED`; this requires the disbursement to be `PAID` (otherwise `ERR_DISBURSEMENT_NOT_PAID`). Voiding is a compensating action: it subtracts the voided amount from `disbursed_total_cents` and recomputes `remaining_obligation_cents`, so the obligation invariant of §2.9 is preserved.

The order in which these guards fire on a disbursement matters. Authentication is checked first, then role authorization, then existence of the path and body identifiers, then the case's state precondition, then that the line item is approved and on the right case, then the segregation and concurrency checks where applicable, then the optimistic-concurrency version match, and finally the fiscal ceiling against the remaining obligation. The full precedence is laid out in §3.11.

### 3.9. Recoupment

A `Recoupment` is an overpayment debt the household owes back to the program. It carries the `ihp_case_id`, an `origin` of `LATE_DOB`, `APPEAL_REDUCTION`, or `MANUAL`, a computed `debt_amount_cents`, a `recovered_cents` running total of what has been clawed back (at least 0, beginning 0), and a `status` of `ESTABLISHED`, `SATISFIED`, or `WAIVED`, beginning `ESTABLISHED`. At establishment, the debt is the larger of zero and the case's `disbursed_total_cents` minus its freshly recomputed `net_eligible_cents` — where "freshly recomputed" means after the triggering cascade has run (the at-recoupment DOB variant for SBA-driven and late-DOB-driven recoupments, and the appeal-override final award for appeal reductions). A recoupment with `LATE_DOB` origin is established by the DOB and SBA cascades of §3.5 and §3.7; one with `APPEAL_REDUCTION` origin is established when an appeal grant reduces the award below what has already been paid (§3.10).

A `ProgramAdmin` records recoveries against an established debt. Each recovery adds its `amount_cents` to the recoupment's `recovered_cents`. When cumulative `recovered_cents` reaches or exceeds `debt_amount_cents`, the recoupment advances `ESTABLISHED → SATISFIED`. Recording a recovery requires the recoupment to be `ESTABLISHED` (otherwise `ERR_RECOUPMENT_NOT_ESTABLISHED`); the satisfaction transition itself is automatic on reaching the threshold, and an attempt to treat the debt as satisfied before cumulative recoveries reach the debt would be `ERR_RECOUPMENT_NOT_FULLY_RECOVERED`. A `ProgramAdmin` may instead forgive the debt, moving it `ESTABLISHED → WAIVED`; this too requires the recoupment to be `ESTABLISHED` (otherwise `ERR_RECOUPMENT_NOT_ESTABLISHED`) and requires no recovery. Both `SATISFIED` and `WAIVED` are terminal.

A case cannot be finalized while it still owes money. A `Caseworker` or `ProgramAdmin` closes a case, moving it `DISBURSING → CLOSED`; this requires the case to be `DISBURSING` (otherwise `ERR_CASE_NOT_DISBURSING`) and requires that no `Recoupment` on the case is in `ESTABLISHED` status (otherwise `ERR_OPEN_RECOUPMENT`).

### 3.10. Appeals and the Cyclic Re-Decision

A household — or a caseworker on its behalf — may contest a determination. A `Caseworker` or `ProgramAdmin` files an `Appeal` carrying the `ihp_case_id`, the `expected_ihp_case_version` for the optimistic-concurrency check of §2.7, the appellant's stated `reason`, and an optional `requested_repair_cost_cents` that, if the appeal is granted, replaces the inspector-verified repair cost when the award is recomputed. The appeal's `status` is `SUBMITTED`, `GRANTED`, or `DENIED`, beginning `SUBMITTED`.

An appeal may be filed only against a case that is `AWARD_APPROVED` or `DENIED` (otherwise `ERR_CASE_NOT_APPEALABLE`), and the `expected_ihp_case_version` must match the case's current `version` (otherwise `ERR_STALE_CASE_VERSION`). Filing advances the case into `UNDER_APPEAL`: from `AWARD_APPROVED → UNDER_APPEAL` it records `pre_appeal_status` as `AWARD_APPROVED`, and from `DENIED → UNDER_APPEAL` it records `pre_appeal_status` as `DENIED`. This `pre_appeal_status` (whose value is one of `AWARD_APPROVED` or `DENIED`) is captured precisely so that a denied appeal can restore the case to exactly the decision it held before. Filing the appeal increments the case's `version` by one.

A `Caseworker` decides the appeal, supplying an `outcome`. The deciding caseworker must not be the case's `determined_by_caseworker_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`, HTTP 403), the case must be `UNDER_APPEAL` (otherwise `ERR_CASE_NOT_UNDER_APPEAL`), and the appeal must be `SUBMITTED` (otherwise `ERR_APPEAL_NOT_SUBMITTED`). The `outcome` must be `GRANTED` or `DENIED`; anything else is `ERR_INVALID_APPEAL_OUTCOME`. Whatever the outcome, the deciding caseworker is recorded in the appeal's `decided_by_caseworker_id` and the case's `version` increments by one.

A **granted** appeal advances the appeal `SUBMITTED → GRANTED` and the case `UNDER_APPEAL → AWARD_APPROVED` regardless of what `pre_appeal_status` held. The award is recomputed in the final variant, but with the appeal's `requested_repair_cost_cents` substituted for the inspector-verified repair cost where the appellant supplied one; `gross_eligible_cents`, `capped_eligible_cents`, and `net_eligible_cents` are recomputed, the line items are re-approved through the cap-and-offset waterfall of §3.6, and `total_approved_cents` is reconciled. If the newly recomputed `net_eligible_cents` is less than the case's `disbursed_total_cents`, an `APPEAL_REDUCTION` `Recoupment` is established for the difference (a transitive cascade off the grant).

A **denied** appeal advances the appeal `SUBMITTED → DENIED` and restores the case to exactly its pre-appeal decision, with all award figures left unchanged — a compensating no-op on the award totals. If `pre_appeal_status` was `AWARD_APPROVED`, the case returns `UNDER_APPEAL → AWARD_APPROVED`; if `pre_appeal_status` was `DENIED`, the case returns `UNDER_APPEAL → DENIED`. In both denied branches the award totals are deliberately untouched. This appeal loop is cyclic: a restored `AWARD_APPROVED` case can be appealed again, filing a new appeal and recording the appropriate `pre_appeal_status` anew.

### 3.11. Rental Assistance Periods

A household with funded rental assistance occupies a coverage timeline made of `RentalAssistancePeriod` records. A `Caseworker` or `ProgramAdmin` opens one with the `ihp_case_id` funding the coverage and a window bounded by `period_start` (inclusive) and `period_end` (exclusive, and required to be strictly after `period_start`). The funding case must be `AWARD_APPROVED` or `DISBURSING` (otherwise `ERR_CASE_NOT_FUNDABLE_FOR_RENTAL`). On creation the period is born `ACTIVE`, and its `applicant_id` is copied from the funding case so the period attaches to the household whose rental timeline it occupies; its `status` is `ACTIVE` or `CLOSED`.

The per-applicant rental timeline is checked for overlap, but with geometry distinct from the inspector calendar of §3.2. Here the interval is half-open and there is no buffer: a new period collides with another `ACTIVE` period of the *same* applicant when the new period's `period_start` is strictly before the other period's `period_end` and the other period's `period_start` is strictly before the new period's `period_end`. Because both comparisons are strict and the end is exclusive, two periods that are exactly adjacent — where one's `period_end` equals the next one's `period_start` — do not collide. A genuine overlap is rejected with `ERR_RENTAL_PERIOD_OVERLAP`. A `Caseworker` or `ProgramAdmin` closes a period, moving it `ACTIVE → CLOSED`; this requires the period to be `ACTIVE` (otherwise `ERR_RENTAL_PERIOD_NOT_ACTIVE`), and once closed it no longer participates in overlap checks, freeing that window of the household's timeline.

### 3.12. Validation Precedence

When several checks could fail on one request, they are evaluated in a fixed priority so the returned error is deterministic. Authentication comes first: missing headers or an unknown role yield `ERR_MISSING_OR_INVALID_AUTH`. Role authorization comes second: a role not permitted for the endpoint yields `ERR_FORBIDDEN_ROLE`. Existence comes third, evaluated left to right — path identifiers before body foreign keys — yielding the resource-specific not-found error. State preconditions come next: the target resource must be in a legal state for the requested transition (for example `ERR_CASE_NOT_PENDING`, `ERR_ASSESSMENT_NOT_SCHEDULED`, `ERR_REFERRAL_NOT_OPEN`), and the cross-entity state precondition that an IHP case's referenced assessment be `VERIFIED` yields `ERR_ASSESSMENT_NOT_VERIFIED`. The applicant-registration temporal gate (`ERR_REGISTRATION_CLOSED`, with the damage-date check yielding `ERR_DAMAGE_DATE_OUT_OF_PERIOD`) belongs to this same family of business preconditions.

After state, the referential check that a disbursement's line item is approved and on the right case yields `ERR_LINE_ITEM_NOT_APPROVED`; the segregation-of-duties check on appeal decisions yields `ERR_SEGREGATION_OF_DUTIES`; the inspector and rental overlap constraints yield `ERR_INSPECTOR_DOUBLE_BOOKED` and `ERR_RENTAL_PERIOD_OVERLAP`; the optimistic-concurrency version match yields `ERR_STALE_CASE_VERSION`; the SBA eligibility gate yields `ERR_SBA_NOT_ELIGIBLE`; and the fiscal ceiling on a disbursement yields `ERR_DISBURSEMENT_EXCEEDS_OBLIGATION`. Last of all comes generic field-level request validation — types, enum membership, required fields, non-negative amounts, and end-after-start ordering — which yields `ERR_INVALID_REQUEST`. The intent of this ordering is that a structural problem (auth, existence) surfaces before a business problem (state, fiscal), and that the fiscal over-draw check is the final business gate before generic shape validation.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, including all state-transition actions and the clock-setting capability, return `200 OK`. All list and detail reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/disaster-relief/_clock/set` | Set the server's logical UTC clock (test-driving) | ProgramAdmin |
| POST | `/disaster-relief/declarations` | Create a disaster declaration | ProgramAdmin |
| GET | `/disaster-relief/declarations` | List disaster declarations | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/declarations/{id}` | Get a disaster declaration | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/declarations/{id}/close-registration` | Close registration | ProgramAdmin |
| POST | `/disaster-relief/declarations/{id}/close` | Close the declaration | ProgramAdmin |
| POST | `/disaster-relief/inspectors` | Create an inspector profile | ProgramAdmin |
| GET | `/disaster-relief/inspectors` | List inspectors | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/inspectors/{id}` | Get an inspector | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/caseworkers` | Create a caseworker profile | ProgramAdmin |
| GET | `/disaster-relief/caseworkers` | List caseworkers | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/caseworkers/{id}` | Get a caseworker | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/applicants` | Register an applicant household | Caseworker, ProgramAdmin |
| GET | `/disaster-relief/applicants` | List applicants | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/applicants/{id}` | Get an applicant | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/applicants/{id}/withdraw` | Withdraw an applicant | Caseworker, ProgramAdmin |
| POST | `/disaster-relief/assessments` | Schedule a damage assessment | Inspector, ProgramAdmin |
| GET | `/disaster-relief/assessments` | List assessments | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/assessments/{id}` | Get a damage assessment | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/assessments/{id}/inspect` | Record inspection results | Inspector |
| POST | `/disaster-relief/assessments/{id}/verify` | Verify an inspected assessment | Caseworker |
| POST | `/disaster-relief/assessments/{id}/cancel` | Cancel a scheduled assessment | Inspector, ProgramAdmin |
| POST | `/disaster-relief/ihp-cases` | Open an IHP case (computes provisional award) | Caseworker |
| GET | `/disaster-relief/ihp-cases` | List IHP cases | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/ihp-cases/{id}` | Get an IHP case | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/ihp-cases/{id}/approve` | Approve eligibility and compute final award | Caseworker |
| POST | `/disaster-relief/ihp-cases/{id}/deny` | Deny eligibility | Caseworker |
| POST | `/disaster-relief/ihp-cases/{id}/close` | Close a case | Caseworker, ProgramAdmin |
| GET | `/disaster-relief/award-line-items` | List award line items | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/award-line-items/{id}` | Get an award line item | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/dob-records` | Record a duplication-of-benefits source | ProgramAdmin, Caseworker |
| GET | `/disaster-relief/dob-records` | List DOB records | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/dob-records/{id}` | Get a DOB record | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/dob-records/{id}/reverse` | Reverse a DOB record | ProgramAdmin |
| POST | `/disaster-relief/appeals` | File an appeal (OCC on the case) | Caseworker, ProgramAdmin |
| GET | `/disaster-relief/appeals` | List appeals | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/appeals/{id}` | Get an appeal | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/appeals/{id}/decide` | Decide an appeal (SoD enforced) | Caseworker |
| POST | `/disaster-relief/sba-referrals` | Refer a case to SBA | Caseworker |
| GET | `/disaster-relief/sba-referrals` | List SBA referrals | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/sba-referrals/{id}` | Get an SBA referral | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/sba-referrals/{id}/record-outcome` | Record the SBA decision | Caseworker, ProgramAdmin |
| POST | `/disaster-relief/disbursements` | Disburse against an approved line item (OCC on the case) | Caseworker |
| GET | `/disaster-relief/disbursements` | List disbursements | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/disbursements/{id}` | Get a disbursement | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/disbursements/{id}/void` | Void a disbursement | ProgramAdmin |
| GET | `/disaster-relief/recoupments` | List recoupments | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/recoupments/{id}` | Get a recoupment | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/recoupments/{id}/record-recovery` | Record a recovery payment | ProgramAdmin |
| POST | `/disaster-relief/recoupments/{id}/waive` | Waive a recoupment debt | ProgramAdmin |
| POST | `/disaster-relief/rental-periods` | Open a rental-assistance coverage period | Caseworker, ProgramAdmin |
| GET | `/disaster-relief/rental-periods` | List rental-assistance periods | ProgramAdmin, Caseworker, Inspector |
| GET | `/disaster-relief/rental-periods/{id}` | Get a rental-assistance period | ProgramAdmin, Caseworker, Inspector |
| POST | `/disaster-relief/rental-periods/{id}/close` | Close a rental-assistance period | Caseworker, ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DECLARATION_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTOR_NOT_FOUND` | 404 Not Found |
| `ERR_CASEWORKER_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICANT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_DOB_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RECOUPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_MISSING_REQUIRED_FIELD` | 422 Unprocessable Entity |
| `ERR_DAMAGE_DATE_OUT_OF_PERIOD` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_CLOSED` | 409 Conflict |
| `ERR_DECLARATION_NOT_OPEN` | 409 Conflict |
| `ERR_DECLARATION_NOT_REGISTRATION_CLOSED` | 409 Conflict |
| `ERR_DECLARATION_CLOSED` | 409 Conflict |
| `ERR_OPEN_DISBURSING_CASES` | 409 Conflict |
| `ERR_APPLICANT_NOT_REGISTERED` | 409 Conflict |
| `ERR_APPLICANT_NOT_INSPECTED` | 409 Conflict |
| `ERR_APPLICANT_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_INSPECTED` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_VERIFIED` | 409 Conflict |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_RENTAL_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CASE_NOT_PENDING` | 409 Conflict |
| `ERR_CASE_NOT_APPROVED` | 409 Conflict |
| `ERR_CASE_NOT_DISBURSING` | 409 Conflict |
| `ERR_CASE_NOT_APPEALABLE` | 409 Conflict |
| `ERR_CASE_NOT_UNDER_APPEAL` | 409 Conflict |
| `ERR_APPEAL_NOT_SUBMITTED` | 409 Conflict |
| `ERR_NO_ELIGIBLE_AMOUNT` | 409 Conflict |
| `ERR_INVALID_APPEAL_OUTCOME` | 422 Unprocessable Entity |
| `ERR_DOB_NOT_RECORDED` | 409 Conflict |
| `ERR_REFERRAL_NOT_OPEN` | 409 Conflict |
| `ERR_SBA_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INVALID_SBA_OUTCOME` | 422 Unprocessable Entity |
| `ERR_LINE_ITEM_NOT_APPROVED` | 409 Conflict |
| `ERR_DISBURSEMENT_EXCEEDS_OBLIGATION` | 402 Payment Required |
| `ERR_DISBURSEMENT_NOT_PAID` | 409 Conflict |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_RECOUPMENT_NOT_ESTABLISHED` | 409 Conflict |
| `ERR_RECOUPMENT_NOT_FULLY_RECOVERED` | 409 Conflict |
| `ERR_OPEN_RECOUPMENT` | 409 Conflict |
| `ERR_RENTAL_PERIOD_NOT_ACTIVE` | 409 Conflict |
| `ERR_CASE_NOT_FUNDABLE_FOR_RENTAL` | 409 Conflict |
