# Neighborhood Infrastructure Petition API — Product Requirements Document

## 1. Introduction

Municipalities fund localized capital improvements — a repaved block, a new sewer lateral, street lighting for a handful of streets — through special assessment districts, in which the cost of the improvement is levied against the very properties it benefits. The Neighborhood Infrastructure Petition API administers the full statutory lifecycle of such a district: a resident petition is circulated and its signatures verified against the property roll; city engineering scopes the project and locks a cost estimate; a statutorily noticed public hearing opens an objection window in which owners can remove their parcels or register protest; the council acts under a protest-weighted voting rule; construction proceeds under seasonal, crew-scheduling, and change-order controls; and a final true-up converts the preliminary roll into definitive levies that owners either prepay or retire through multi-year installment schedules with delinquency handling.

The program is deliberately actor-segregated: the clerk shepherds districts, parcels, petitions, and hearings; the engineer owns estimates, phases, and change orders; the finance officer runs the true-up, billing sweeps, and refunds; the council president records resolutions and grants final acceptance; and property owners act only on resources tied to parcels they own. Because statutory deadlines, seasonal windows, grace periods, and interest accrual all depend on the current time, the server evaluates every temporal rule against a logical clock that tests can advance deterministically (§2.4). All monetary values are carried as integer cents end to end, and every allocation, penalty, and payoff figure is produced by a pinned calculation procedure so that two independent implementations agree to the cent (§2.6).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. Six roles are recognized, spelled exactly as follows: `SystemAdmin`, `CityClerk`, `CityEngineer`, `FinanceOfficer`, `CouncilPresident`, and `PropertyOwner`. A request missing either header, or carrying a role outside this list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); a header present but carrying an empty value counts as missing. When the supplied role is not among the roles an endpoint admits, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `PropertyOwner`, `X-User-ID` is the `id` of the acting **PropertyOwner** record; ownership checks on any resource that references a property owner — a signature's parcel, an objection's parcel, an assessment's parcel — compare the resource's owner-of-record field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `SystemAdmin`, `CityClerk`, `CityEngineer`, `FinanceOfficer`, or `CouncilPresident`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where workflows attribute actions — as `submitted_by` on a cost estimate, `verified_by` on a signature, `reviewed_by` on an objection, `recorded_by` on a resolution, or `proposed_by_user_id` / `decided_by_user_id` on a change order — but it is never compared against any entity's `id`, except that change-order approval compares the caller's `X-User-ID` against the order's recorded `proposed_by_user_id` (§3.6).

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

Requests that never reach an endpoint also answer in this envelope: an undefined path is rejected with `ERR_NOT_FOUND` (HTTP 404), an unsupported method on a defined path with `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server failure with `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

Six listings paginate through two query parameters: the district list, the owner list, the parcel list, and the district's parcel, parcel-assessment, and invoice listings. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100 — an out-of-range value is clamped to the nearest bound and a non-integer value falls back to the default. The `offset` parameter skips a number of items and defaults to 0; a negative value is clamped to 0 and a non-integer value falls back to the default. `has_more` is true exactly when `offset` plus `limit` is less than `total_count`. Every other list endpoint returns its full result set unpaginated, ignoring `limit` and `offset`. Both paginated and non-paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; on an unpaginated listing `limit` equals `total_count`, `offset` is 0, and `has_more` is false.

Unless a listing documents otherwise, resources sort by `created_at` in ascending order. Three documented exceptions exist: parcel listings and parcel-assessment listings order by `parcel_number` ascending, and invoice listings order by `due_date` ascending. Ties on the documented sort key fall back to `created_at` ascending and then to creation order; for the default `created_at` ordering, ties fall back to creation order. Several listings accept additional filters, noted per endpoint in §4 — a `status` filter on the district, parcel-assessment, and invoice listings, and `district_id` or `owner_id` filters on the parcel listing.

### 2.4. The Logical Clock

The server keeps a logical clock, and every temporal rule in this document — statutory notice periods, objection windows, payment-option deadlines, season containment, phase start gates, invoice issue and due dates, delinquency grace — evaluates "now" against that clock, never against wall-clock time. Before any clock-setting call, the logical clock reads exactly `2026-08-01T00:00:00Z`. The clock is advanced exclusively through an admin-only, test-driving capability mounted at `/_clock/set_current_utc`, which accepts a target instant `to_iso8601` and answers with the resulting `current_utc`; this capability is reserved to `SystemAdmin`. System-stamped timestamps throughout the system — the response envelope's `api_request_timestamp`, a petition's `opened_at`, a signature's `signed_at`, an objection's `filed_at`, a payment's `received_at`, and the like — are all read from this clock.

### 2.5. Common Resource Properties

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All resources except one additionally carry `updated_at`, refreshed on every mutation, and a `version` integer that starts at 1 at creation — when `created_at` and `updated_at` coincide — and increments by one with every modification to that resource and that anchors the optimistic-concurrency rules of §2.7. The single exception is the **Payment**: a payment is an append-only event and carries only `id` and `created_at` — `updated_at` and `version` are absent, because a payment is never modified after posting.

### 2.6. Money, Frontage, and Percentage Precision

All monetary values — estimates, levies, invoice components, payments, credits — are integer cents at every step; there is no floating-point money anywhere in the system. Frontage measurements (`frontage_ft`, and district or petition aggregates of it) are carried at two decimal places. Percentages — petition support figures and the protest weight — are computed to exactly two decimal places with round-half-up, and threshold comparisons consume the rounded value. One intermediate rate is held finer: the per-foot allocation rate of §3.3 is rounded half-up to four decimal places before any per-parcel multiplication, and only the resulting parcel amounts are rounded half-up to whole cents. Wherever this document says an amount is "rounded", the method is round half up at the stated precision.

### 2.7. Optimistic Concurrency Control

Three write operations are version-checked against their parent aggregate, and each names its expectation field in the request body. Submitting a cost estimate requires `expected_district_version` equal to the district's current `version`. Recording a council resolution likewise requires `expected_district_version`. Posting a payment requires `expected_parcel_assessment_version` equal to the assessment's current `version`. In all three cases the field is non-optional, and a mismatch with the parent's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a client from writing against a state of the aggregate it has not observed. Endpoints not named here take no version field.

### 2.8. Validation Order and Resource Retrieval

Every endpoint applies its checks in a single fixed priority order, and the first failure wins — later checks are never evaluated once an earlier one has failed. The order is:

1. **Request shape** (HTTP 400, `ERR_INVALID_REQUEST`): required fields present, types correct, enum members valid, date and MM-DD formats valid, and scalar ranges enforced — `frontage_ft` strictly positive, `votes_for` and `votes_against` each between 0 and 5 with a combined total of at most 5, `annual_interest_rate_bp` between 0 and 2000 inclusive, `contract_price_cents` strictly positive, `contingency_cents` zero or greater, `estimated_cost_cents` strictly positive, and `end_date` no earlier than `start_date`. Unrecognized body fields are ignored; an absent body is treated as an empty object, while a malformed or non-object JSON body fails this step.
2. **Authentication headers** (HTTP 400, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) on every endpoint.
3. **Role authorization** (HTTP 403, `ERR_UNAUTHORIZED_ROLE`) on every endpoint.
4. **Existence** (HTTP 404): identifiers are validated left to right — path identifiers first, then body foreign keys in their declared input order. Each resource type has its own error: `ERR_DISTRICT_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_SIGNATURE_NOT_FOUND`, `ERR_COST_ESTIMATE_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_OBJECTION_NOT_FOUND`, `ERR_RESOLUTION_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, and `ERR_PAYMENT_NOT_FOUND`. A request aimed at a missing parent therefore reports the parent's absence before any child identifier is examined.
5. **Ownership** (HTTP 403, `ERR_NOT_RESOURCE_OWNER`) on the seven owner-scoped operations: signing a petition, withdrawing a signature, filing an objection, withdrawing an objection, selecting a payment option, requesting a payoff quote as the owner, and posting a payment.
6. **Segregation of duties** (HTTP 403, `ERR_SEGREGATION_OF_DUTIES`) on change-order approval only.
7. **Optimistic concurrency** (HTTP 412, `ERR_STALE_VERSION`) on the three version-checked writes of §2.7.
8. **State preconditions** (HTTP 409): the district phase gates (`ERR_DISTRICT_NOT_DRAFT`, `ERR_DISTRICT_NOT_IN_SCOPING`, `ERR_NO_APPROVED_ESTIMATE`, `ERR_DISTRICT_NOT_IN_OBJECTION_WINDOW`, `ERR_DISTRICT_NOT_IN_COUNCIL_REVIEW`, `ERR_DISTRICT_NOT_APPROVED_OR_UNDER_CONSTRUCTION`, `ERR_DISTRICT_NOT_IN_CONSTRUCTION`, `ERR_DISTRICT_NOT_IN_TRUE_UP`, `ERR_DISTRICT_NOT_IN_BILLING`, `ERR_DISTRICT_NOT_ACCEPTABLE`, `ERR_DISTRICT_NOT_ABANDONABLE`) and the per-entity state errors (`ERR_PETITION_NOT_CIRCULATING`, `ERR_SIGNATURE_NOT_VERIFIABLE`, `ERR_SIGNATURE_NOT_WITHDRAWABLE`, `ERR_ESTIMATE_NOT_SUBMITTED`, `ERR_HEARING_NOT_SCHEDULED`, `ERR_OBJECTION_NOT_FILED`, `ERR_OBJECTION_NOT_UNDER_REVIEW`, `ERR_ASSESSMENT_NOT_LEVIED`, `ERR_ASSESSMENT_OPTION_ALREADY_SELECTED`, `ERR_PHASE_NOT_PLANNED`, `ERR_PHASE_NOT_IN_PROGRESS`, `ERR_CHANGE_ORDER_NOT_PROPOSED`), along with the workflow-level blockers `ERR_UNRESOLVED_OBJECTIONS`, `ERR_PHASES_NOT_ALL_COMPLETE`, `ERR_ASSESSMENTS_NOT_ALL_PAID`, and `ERR_REMAND_LIMIT_EXCEEDED`.
9. **Statutory notice** (HTTP 422, `ERR_HEARING_NOTICE_TOO_SHORT`) on hearing scheduling.
10. **Temporal windows** (HTTP 422): `ERR_OBJECTION_WINDOW_CLOSED`, `ERR_OBJECTION_WINDOW_STILL_OPEN`, `ERR_PAYMENT_OPTION_WINDOW_CLOSED`, `ERR_SEASON_WINDOW_VIOLATION`, `ERR_PHASE_START_NOT_REACHED`, and `ERR_HEARING_DATE_NOT_REACHED`, guarding objection filing, payment-option selection, prepayment, phase planning and starting, record-held, and objection-window closing respectively.
11. **Referential coherence** (HTTP 422): `ERR_PARCEL_NOT_IN_DISTRICT` when a signature's or objection's parcel lies outside the petition's or hearing's district, and `ERR_PHASE_NOT_IN_DISTRICT` when a change order's linked phase lies outside the change order's district.
12. **Uniqueness and resource conflicts** (HTTP 409): `ERR_DUPLICATE_PARCEL_NUMBER`, `ERR_DUPLICATE_OWNER_EMAIL`, `ERR_DUPLICATE_SIGNATURE`, `ERR_DUPLICATE_OBJECTION`, `ERR_INELIGIBLE_PARCEL`, `ERR_PHASE_SCHEDULE_CONFLICT`, `ERR_CONSTRUCTION_CAPACITY_EXCEEDED`, and `ERR_VENUE_DATE_CONFLICT`.
13. **Fiscal rules, last** (HTTP 422 unless noted): `ERR_INVALID_AMOUNT`, `ERR_OVERPAYMENT` (HTTP 402), `ERR_INVALID_PREPAY_AMOUNT`, `ERR_REFUND_EXCEEDS_CREDIT`, and `ERR_TERM_NOT_ALLOWED`.

Because this ordering is observable, a request that violates several rules always reports the earliest one: a malformed body beats an unknown role, an unknown role beats a missing resource, a missing resource beats an ownership failure, and a stale version is detected before any state, temporal, or fiscal rule runs.

### 2.9. District Versioning and Lifecycle Cascades

The district is the program's aggregate root, and nearly every lifecycle event advances its `version` by one and refreshes its `updated_at`: opening or closing a petition, adding a parcel, submitting an estimate, scheduling or recording a hearing, closing the objection window, recording any resolution, starting the first construction phase, completing construction, approving a change order, finalizing the true-up, accepting, and abandoning. Lifecycle events also cascade into child resources to keep the tree consistent: petitions and their signatures are voided, estimates and preliminary assessments superseded, hearings voided or superseded, and objections withdrawn, each at the moment the district's own state makes them moot. The individual cascades are specified with their workflows in §3; the invariant is that no child resource is left claiming participation in a phase the district has already exited.

### 2.10. The Eligibility Denominator

Two parcel properties decide whether a piece of land participates in the program at all. A parcel marked `exempt` — and any parcel whose `status` has become `REMOVED` — cannot sign petitions, is excluded from every eligibility denominator, receives no assessment, and cannot be the target of a new objection; attempting to sign or object for such a parcel is rejected with `ERR_INELIGIBLE_PARCEL` (HTTP 409). The district's `total_frontage_ft` and `eligible_parcel_count` are defined over exactly the participating set — parcels that are `ACTIVE` and not exempt — and are recomputed whenever that set changes: when parcels are added during `DRAFT`, and when a sustained objection removes one during the objection window.

## 3. Business Logic & Workflows

### 3.1. Standing Up a District and Its Property Roll

A `CityClerk` opens a new program by creating the **District** itself, supplying a display `name`, the assessment `methodology` (`PER_PARCEL` or `FRONT_FOOT`), and the delinquency `interest_method` (`SIMPLE` or `COMPOUND`) that will govern penalty accrual years later. Three numeric and two seasonal parameters complete the profile: `annual_interest_rate_bp` carries the installment interest rate in basis points, defaulting to 400 when omitted and bounded inclusively between 0 and 2000; `season_start_mmdd` and `season_end_mmdd` delimit the legal construction season as MM-DD strings, both bounds inclusive, and the season may not wrap the calendar year-end, so the start bound must fall on or before the end bound. Malformed values or out-of-range numbers are rejected with `ERR_INVALID_REQUEST`. A new district begins in `DRAFT`: `remand_count` starts at zero, the derived roll totals `total_frontage_ft` and `eligible_parcel_count` start at zero, `protest_frontage_pct`, `approved_estimate_id`, `final_total_cost_cents`, `levy_date`, and `payment_option_deadline` are all unset, `approved_change_total_cents`, `paid_assessment_count`, and `total_assessment_count` start at zero, and `overrun_flag` and `all_assessments_paid` start false.

The property roll is built next. The clerk registers each **PropertyOwner** with `full_name`, `email`, and `mailing_address`; the email is globally unique, judged on the exact string supplied, and a second registration under an existing address of record is refused with `ERR_DUPLICATE_OWNER_EMAIL`. Parcels then attach to the district — but only while the district remains `DRAFT`; once petitioning has begun the roll is frozen and a late addition fails with `ERR_DISTRICT_NOT_DRAFT`. Each **Parcel** carries the `district_id` it joins, the `owner_id` of its owner of record, an assessor `parcel_number` unique within its district (`ERR_DUPLICATE_PARCEL_NUMBER`), a strictly positive `frontage_ft` carried at two decimal places — a value supplied at finer precision is rounded half-up to two decimals at registration, with the positivity check applied to the rounded value — and an `exempt` flag defaulting to false. Every accepted parcel immediately recomputes the district's `total_frontage_ft` and `eligible_parcel_count` and advances the district's `version` by one. A parcel's own `status` begins at `ACTIVE` and only ever leaves it for `REMOVED`, the consequence of a sustained objection (§3.4).

Across its life a district walks the status spine `DRAFT` → `PETITIONING` → `SCOPING` → `HEARING_SCHEDULED` → `OBJECTION_WINDOW` → `COUNCIL_REVIEW` → `APPROVED` → `CONSTRUCTION` → `TRUE_UP` → `BILLING` → `ACCEPTED`, with `ABANDONED` as the alternate terminal outcome and two sanctioned loops — re-circulation from `PETITIONING` back to `DRAFT`, and council remand from `COUNCIL_REVIEW` back to `SCOPING` — detailed in the sections that follow.

### 3.2. Petition Circulation and Signature Verification

Opening a petition is the clerk's act that moves a district from `DRAFT` into `PETITIONING`; attempting it in any other district state fails with `ERR_DISTRICT_NOT_DRAFT`. The new **Petition** records its `district_id` — one petition per district circulation cycle — opens in `CIRCULATING` with `opened_at` stamped from the logical clock, and starts with `verified_signature_count` and `verified_frontage_ft` at zero; `closed_at`, both snapshots, and both percentages remain unset until close. The district's `version` advances on the open.

While the petition circulates, a `PropertyOwner` signs it for their own parcel by submitting `petition_id` and `parcel_id`. The caller must be the parcel's owner of record (`ERR_NOT_RESOURCE_OWNER`), the parcel must belong to the petition's district (`ERR_PARCEL_NOT_IN_DISTRICT`), the parcel must be eligible — exempt or `REMOVED` parcels cannot sign (`ERR_INELIGIBLE_PARCEL`) — and the petition must still be `CIRCULATING` (`ERR_PETITION_NOT_CIRCULATING`). A parcel holds at most one live signature per petition: a second submission while a `SUBMITTED` or `VERIFIED` signature exists for the same parcel on the same petition is refused with `ERR_DUPLICATE_SIGNATURE`, which is also why a parcel can never contribute more than one verified signature to the tallies. An accepted **PetitionSignature** records the signing owner in `owner_id` — taken from the caller's `X-User-ID`, never from the request body — stamps `signed_at`, and lands in `SUBMITTED`.

Verification is the clerk's desk work. Verifying requires the signature still be `SUBMITTED` (`ERR_SIGNATURE_NOT_VERIFIABLE`), the petition still `CIRCULATING` (`ERR_PETITION_NOT_CIRCULATING`), the parcel still `ACTIVE` and non-exempt at verification time (`ERR_INELIGIBLE_PARCEL`), and the signature's owner still match the parcel's owner of record (`ERR_NOT_RESOURCE_OWNER`). A verified signature moves to `VERIFIED`, stamps `verified_at`, records the clerk in `verified_by`, and adds one to the petition's `verified_signature_count` and the parcel's `frontage_ft` to `verified_frontage_ft`. Rejection takes the sibling path from `SUBMITTED` under the same two circulation-and-state gates: the clerk supplies a `reason`, stored on the signature as `rejection_reason`, and the signature becomes `REJECTED`. Verification and withdrawal also refresh the petition's `updated_at` and advance its `version`; submission and rejection leave the petition itself untouched.

The owner retains a veto over their own mark. Withdrawal is available to the signature's owner (`ERR_NOT_RESOURCE_OWNER`) from either `SUBMITTED` or `VERIFIED`, but only while the petition still circulates — once circulation has closed, withdrawal fails with `ERR_SIGNATURE_NOT_WITHDRAWABLE`. Withdrawal stamps `withdrawn_at`; withdrawing a `VERIFIED` signature additionally decrements `verified_signature_count` by one and subtracts the parcel's `frontage_ft` from `verified_frontage_ft`, keeping the petition's tallies conserved against the set of signatures currently `VERIFIED`.

Closing circulation is the clerk's final act on a petition, and only a `CIRCULATING` petition can be closed (`ERR_PETITION_NOT_CIRCULATING`). At close the petition freezes its evidence: `closed_at` is stamped, `eligible_parcel_count_snapshot` captures the district's `eligible_parcel_count`, and `eligible_frontage_snapshot` captures its `total_frontage_ft`, both taken at that instant. Two support percentages are computed from only the signatures `VERIFIED` at close: `support_count_pct` is the verified signature count divided by the eligible parcel snapshot, multiplied by one hundred and rounded half-up to two decimal places, and `support_frontage_pct` is the verified frontage divided by the eligible frontage snapshot on the same rounding rule. Passage requires both — a count percentage of at least 60.00 and a frontage percentage of at least 50.00 — so a district can pass on parcels yet fail on frontage, or the reverse, on an identical signature set. A petition that meets both thresholds closes `CLOSED_VERIFIED` and moves the district `PETITIONING` → `SCOPING`; one that misses either threshold closes `CLOSED_INSUFFICIENT` and returns the district to `DRAFT`, where a fresh petition may be opened for a new cycle. If not a single eligible parcel exists at close, the petition auto-fails to `CLOSED_INSUFFICIENT`, recording both support percentages as 0.00. Either close outcome advances the district's `version`.

### 3.3. Engineering Scoping, Cost Estimates, and the Preliminary Roll

With the district in `SCOPING`, a `CityEngineer` submits **CostEstimate** records carrying `district_id`, a strictly positive `contract_price_cents`, and a zero-or-greater `contingency_cents` — violations of either range are `ERR_INVALID_REQUEST`. Each estimate is stamped with a per-district `estimate_seq` beginning at 1 and assigned in creation order, records the submitting engineer's header identity in `submitted_by`, derives `total_estimated_cost_cents` as the sum of contract price and contingency, and lands in `SUBMITTED`. Submitting in a district that is not in `SCOPING` fails with `ERR_DISTRICT_NOT_IN_SCOPING`. Because a fresh submission legitimately supersedes any estimate of the district still `SUBMITTED`, the create must carry `expected_district_version` matching the district's current `version`; a writer holding a stale district view is refused with `ERR_STALE_VERSION` (HTTP 412) rather than allowed to overwrite a district state it never observed. A successful submission also advances the district's `version` by one.

Approval distinguishes the working figure. An engineer approves an estimate only while it is `SUBMITTED` (`ERR_ESTIMATE_NOT_SUBMITTED`) and only while the district remains in `SCOPING` (`ERR_DISTRICT_NOT_IN_SCOPING`); approval moves the estimate to `APPROVED` and supersedes any other `APPROVED` estimate of the district, so at most one approved estimate stands at any time. Estimates also leave the board without action: a `SUBMITTED` estimate is superseded when a newer estimate is created, and both `SUBMITTED` and `APPROVED` estimates become `SUPERSEDED` on a council remand or an abandonment.

The hearing converts the estimate into a roll. The clerk schedules the **PublicHearing** with `district_id`, `hearing_date`, and `venue`, but only while the district is in `SCOPING` (`ERR_DISTRICT_NOT_IN_SCOPING`) and only with an `APPROVED` estimate on record (`ERR_NO_APPROVED_ESTIMATE`). Statutory notice requires `hearing_date` to fall at least ten days after the scheduling instant (`ERR_HEARING_NOTICE_TOO_SHORT`). The calendar is venue-exclusive at whole-day granularity: if any hearing still `SCHEDULED` or `HELD` — in any district, not only this one — already occupies the same `venue` string on the same UTC calendar date, the request is rejected with `ERR_VENUE_DATE_CONFLICT`; adjacent dates need no buffer. A scheduled hearing opens in `SCHEDULED` with `objection_window_end` fixed at fifteen days after `hearing_date`.

Scheduling performs two locks. First, the district's `approved_estimate_id` is pinned to the currently approved estimate — a plain reference held on the district, not a containment link — so later estimate churn cannot move the basis of the roll. Second, the preliminary allocation runs against that locked estimate's `total_estimated_cost_cents`, minting one **ParcelAssessment** in `PRELIMINARY` for every `ACTIVE` non-exempt parcel, each stamped with its `district_id` and `parcel_id` and carrying its computed `preliminary_amount_cents`. The district advances to `HEARING_SCHEDULED` and its `version` increments.

The allocation procedure is pinned to the cent and comes in the district's two methodology variants. Under `FRONT_FOOT`, a per-foot rate is computed first: the estimate total divided by the summed `frontage_ft` of the participating parcels, rounded half-up to four decimal places; each parcel's raw amount is then its own frontage times that rate, rounded half-up to whole cents. Under `PER_PARCEL`, a single equal share is computed — the estimate total divided by the participating parcel count, rounded half-up to whole cents — and every parcel receives that share. Both variants then reconcile the penny remainder identically: the difference between the estimate total and the sum of allocated amounts, which may be positive or negative, is walked off parcel by parcel in a pinned visiting order — `frontage_ft` descending, ties broken by `created_at` ascending — adding or subtracting one cent per parcel to match the sign of the difference until it is exhausted, wrapping around to the head of the order if the absolute difference exceeds the parcel count. After reconciliation the allocated amounts sum to the estimate total exactly. The rounding order is part of the contract: rate to four decimals first, then the per-parcel multiplication, then whole-cent rounding, then remainder reconciliation — summing raw values and rounding once at the end yields different cents and is wrong.

### 3.4. The Public Hearing, Objections, and Protest Weight

Once the hearing instant has arrived, the clerk records the hearing as held. Only a `SCHEDULED` hearing can be recorded (`ERR_HEARING_NOT_SCHEDULED`), and recording before `hearing_date` fails with `ERR_HEARING_DATE_NOT_REACHED`. The hearing moves `SCHEDULED` → `HELD`, the district moves `HEARING_SCHEDULED` → `OBJECTION_WINDOW`, and the district's `version` advances — the objection window is now open.

During the window — while the current time is on or before `objection_window_end`; filings after that instant fail with `ERR_OBJECTION_WINDOW_CLOSED` — a `PropertyOwner` files an **Objection** against their own parcel, supplying `hearing_id`, `parcel_id`, and free-text `grounds`. The caller must own the parcel (`ERR_NOT_RESOURCE_OWNER`), the parcel must belong to the hearing's district (`ERR_PARCEL_NOT_IN_DISTRICT`), and the parcel must be eligible — exempt or already `REMOVED` parcels cannot be objected (`ERR_INELIGIBLE_PARCEL`). A parcel carries at most one live objection per hearing: a second filing while one stands `FILED` or `UNDER_REVIEW` meets `ERR_DUPLICATE_OBJECTION`. The objection inherits its `district_id` from the hearing, records the filing owner in `owner_id` from the caller's header, stamps `filed_at`, and opens in `FILED`.

Adjudication is a two-step clerk workflow. Taking an objection under review requires it be `FILED` (`ERR_OBJECTION_NOT_FILED`), records the clerk in `reviewed_by`, and moves it to `UNDER_REVIEW`. Deciding it — in either direction — requires the objection be `UNDER_REVIEW` (`ERR_OBJECTION_NOT_UNDER_REVIEW`) and the district still sit in `OBJECTION_WINDOW` (`ERR_DISTRICT_NOT_IN_OBJECTION_WINDOW`).

Sustaining an objection fires a three-hop cascade. The parcel itself is removed, `ACTIVE` → `REMOVED`. Its `PRELIMINARY` assessment is removed with it, `PRELIMINARY` → `REMOVED`. Then the preliminary allocation re-runs over the remaining `ACTIVE` non-exempt parcels against the same locked estimate total — same methodology variant, same four-decimal rate rule, same remainder order — rewriting every surviving sibling's `preliminary_amount_cents`, while the district's `total_frontage_ft` and `eligible_parcel_count` are recomputed over the shrunken roll. The objection lands in `SUSTAINED` with `adjudicated_at` stamped.

Overruling is the symmetric decision with none of the cascade: the objection moves to `OVERRULED`, `adjudicated_at` is stamped, and the parcel and its assessment stand unchanged. The overruled parcel is not invisible, though — its frontage still counts toward the protest weight computed at window close.

The filing owner may also withdraw their objection, but only while it is `FILED` (`ERR_OBJECTION_NOT_FILED` once it has moved on; `ERR_NOT_RESOURCE_OWNER` for anyone but the filer); a `WITHDRAWN` objection contributes nothing further.

When the window has run its course, the clerk closes it. Closing requires the district be in `OBJECTION_WINDOW` (`ERR_DISTRICT_NOT_IN_OBJECTION_WINDOW`), requires the current time be strictly past `objection_window_end` — at or before that instant the close is premature and fails with `ERR_OBJECTION_WINDOW_STILL_OPEN` — and requires that no objection of the district remain `FILED` or `UNDER_REVIEW` (`ERR_UNRESOLVED_OBJECTIONS`). The close then computes and stores the district's `protest_frontage_pct`, unset until this moment: the summed `frontage_ft` of parcels holding an `OVERRULED` objection, divided by the summed frontage of all `ACTIVE` non-exempt parcels, multiplied by one hundred and rounded half-up to two decimal places. `WITHDRAWN` and `SUSTAINED` objections contribute zero to the numerator, and because sustained parcels are by then `REMOVED`, their frontage leaves the denominator as well; should no eligible frontage remain at all, the close is rejected with `ERR_UNRESOLVED_OBJECTIONS`. A successful close moves the hearing `HELD` → `CLOSED`, the district `OBJECTION_WINDOW` → `COUNCIL_REVIEW`, and increments the district's `version`.

### 3.5. Council Action: Resolutions, Remand, and Levy

With the district in `COUNCIL_REVIEW`, the `CouncilPresident` records each **CouncilResolution**, supplying `district_id`, the `motion` — `APPROVE`, `REJECT`, or `REMAND` — and the tallies `votes_for` and `votes_against`. The council seats five members: each tally must lie between 0 and 5 inclusive and their sum may not exceed 5, with violations rejected as `ERR_INVALID_REQUEST`. Recording is possible only while the district sits in `COUNCIL_REVIEW` (`ERR_DISTRICT_NOT_IN_COUNCIL_REVIEW`), and because every recorded resolution mutates district state, the request must carry `expected_district_version` matching the district's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) when the caller's view is stale. Each recorded resolution persists the district's `protest_frontage_pct` at recording time into `protest_pct_snapshot`, the computed threshold into `required_votes_snapshot`, and the recording president's identity into `recorded_by`, and the district's `version` advances on every recorded resolution, whatever its outcome.

The vote rule is protest-weighted. When the protest percentage stands at 50.00 or higher, an approval motion requires a supermajority of 4 votes; below that mark, a simple majority of 3 suffices. The computed `outcome` — `ADOPTED` or `FAILED` — follows the motion: an `APPROVE` motion is adopted exactly when `votes_for` reaches the required threshold; a `REJECT` motion is adopted with at least 3 votes in favor; a `REMAND` motion is adopted with at least 3 votes in favor, provided the district's `remand_count` is still below its hard cap of 2 — a remand attempted when two remands have already been executed is rejected outright with `ERR_REMAND_LIMIT_EXCEEDED`.

The district then follows the outcome. An adopted `APPROVE` moves the district to `APPROVED` and levies the roll: every `PRELIMINARY` assessment becomes `LEVIED` with its `principal_balance_cents` initialized to its `preliminary_amount_cents`, the district's `levy_date` is stamped with the current time, and `payment_option_deadline` is fixed at thirty days after the levy. A failed `APPROVE`, or an adopted `REJECT`, abandons the district — it moves to `ABANDONED`, its hearing is voided, and every `PRELIMINARY` assessment is superseded. A failed `REJECT` and a failed `REMAND` both leave the district in `COUNCIL_REVIEW`, where further resolutions may be recorded. An adopted `REMAND` sends the district back to `SCOPING` with the full remand cascade: `remand_count` increases by one, the `CLOSED` hearing becomes `SUPERSEDED`, every `PRELIMINARY` assessment becomes `SUPERSEDED`, the currently `APPROVED` estimate becomes `SUPERSEDED`, and `approved_estimate_id` is cleared — engineering must re-estimate and re-approve before any new hearing can be scheduled.

### 3.6. Construction: Phases, Crews, and Change Orders

Once the district is `APPROVED`, engineering plans the build as a set of **ConstructionPhase** records, each carrying `district_id`, a `name`, the `crew_name` staffing it, inclusive `start_date` and `end_date` calendar dates, and a strictly positive `estimated_cost_cents`. Planning is open only while the district is `APPROVED` or already under `CONSTRUCTION` (`ERR_DISTRICT_NOT_APPROVED_OR_UNDER_CONSTRUCTION`), and each new phase must clear three scheduling checks. First, season containment: every calendar date of the new phase's inclusive range must fall inside the district's construction season for that date's calendar year, both season bounds inclusive; any date outside the season yields `ERR_SEASON_WINDOW_VIOLATION`. Second, the crew buffer: against every existing `PLANNED` or `IN_PROGRESS` phase of the same district sharing the same `crew_name`, the two ranges must be separated by at least five calendar days on one side or the other — the new phase starting at least five days after the existing phase ends, or the existing phase starting at least five days after the new phase ends — and a gap of exactly five days passes; anything tighter raises `ERR_PHASE_SCHEDULE_CONFLICT`. Third, concurrent capacity: on every calendar date the new phase covers, the number of existing `PLANNED` or `IN_PROGRESS` phases of the district already covering that date must be below two, so that at most two phases ever run concurrently counting the new one; a third overlapping phase is refused with `ERR_CONSTRUCTION_CAPACITY_EXCEEDED`. A planned phase opens in `PLANNED`.

Execution follows a small machine. Starting a phase requires it be `PLANNED` (`ERR_PHASE_NOT_PLANNED`), the district be `APPROVED` or `CONSTRUCTION` (`ERR_DISTRICT_NOT_APPROVED_OR_UNDER_CONSTRUCTION`), and the current time to have reached midnight UTC at the start of the phase's `start_date` (`ERR_PHASE_START_NOT_REACHED`); starting stamps `started_at`, moves the phase to `IN_PROGRESS`, and — when it is the first phase to start — moves the district from `APPROVED` to `CONSTRUCTION`, incrementing the district's `version`. Completing requires the phase be `IN_PROGRESS` (`ERR_PHASE_NOT_IN_PROGRESS`) and stamps `completed_at`, landing it in `COMPLETED`. Cancelling is permitted only from `PLANNED` — any other status fails with `ERR_PHASE_NOT_PLANNED` — and lands the phase in `CANCELLED`. Both terminal outcomes are final.

Scope changes arrive as **ChangeOrder** proposals, open only while the district is in `CONSTRUCTION` (`ERR_DISTRICT_NOT_IN_CONSTRUCTION`), carrying `district_id`, a free-text `description`, a strictly positive `amount_cents` (`ERR_INVALID_AMOUNT`), and an optional `phase_id` pinning the overrun to a phase — which, when present, must belong to the same district as the change order (`ERR_PHASE_NOT_IN_DISTRICT`). The proposer's header identity is captured in `proposed_by_user_id`, and the order opens in `PROPOSED`.

Approval is deliberately a different pair of hands: the deciding engineer's `X-User-ID` must differ from `proposed_by_user_id`, and a self-approval is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The order must still be `PROPOSED` (`ERR_CHANGE_ORDER_NOT_PROPOSED`) and the district still in `CONSTRUCTION`. Approving records the decider in `decided_by_user_id`, adds the order's `amount_cents` into the district's `approved_change_total_cents`, recomputes the district's `overrun_flag`, and advances the district's `version`. The overrun rule is strict: the flag is true exactly when the cumulative approved change total is strictly greater than one tenth of the locked estimate's `contract_price_cents`, the cap itself rounded half-up to whole cents — landing exactly on the cap is not an overrun. Rejection, under the same state gates, records `decided_by_user_id` and moves the order to `REJECTED`, touching no totals.

When the work is finished, the engineer completes construction. The district must be in `CONSTRUCTION` (`ERR_DISTRICT_NOT_IN_CONSTRUCTION`), at least one phase must exist, and every phase must be terminal — `COMPLETED` or `CANCELLED` — with at least one `COMPLETED` among them; otherwise the request fails with `ERR_PHASES_NOT_ALL_COMPLETE`. The district advances to `TRUE_UP` and its `version` increments.

### 3.7. True-Up: Final Levy, Prepaid Deltas, and Installment Schedules

The true-up belongs to the `FinanceOfficer` and requires the district to be in `TRUE_UP` (`ERR_DISTRICT_NOT_IN_TRUE_UP`). Its first act is accounting: the district's `final_total_cost_cents` becomes the locked estimate's `contract_price_cents` plus the cumulative `approved_change_total_cents` — the `contingency_cents` allowance is deliberately excluded from the final basis. That final basis is then allocated across the `ACTIVE` non-exempt parcels by exactly the same pinned procedure as the preliminary roll — the district's `methodology` selecting the four-decimal front-foot rate or the equal per-parcel share, with the same penny-remainder walk in frontage-descending, creation-ascending order — and each levy-bearing assessment's `final_levy_cents`, unset until now, is set from it. Because the provisional basis included contingency while the final basis excludes it and adds approved changes, identical parcels generally receive different per-parcel figures at the two steps, and that per-parcel delta is what drives the settlements below.

Assessments then settle by payment posture. Any `LEVIED` assessment whose owner never made an election — `payment_option` still `NONE` — is defaulted into `INSTALLMENTS` with a `term_years` of 10, and because the owner made no election, `option_selected_at` remains unset. A `LEVIED` assessment whose owner elected `PREPAY_FULL` but never posted the prepayment settles through the prepaid comparison below against the amount actually paid — zero — and so lands in `SETTLEMENT_DUE` with a supplemental invoice for the entire final levy. A `PREPAID` assessment compares its `final_levy_cents` against the `preliminary_amount_cents` already paid: when the final levy is strictly greater, the assessment moves to `SETTLEMENT_DUE`, its `principal_balance_cents` becomes the delta, and a supplemental **InstallmentInvoice** — `kind` set to `SUPPLEMENTAL` — is created directly in `ISSUED` for exactly the delta, with `year_index` 0, its `issue_date` at the true-up instant, its `due_date` thirty days later, zero `interest_cents`, and `penalty_cents` and `paid_cents` starting at zero; when the final levy is equal to or less than what was paid, the assessment moves straight to `PAID_OFF`, and when it is strictly less, the overage is parked as a refundable `credit_balance_cents` equal to the shortfall. Either way the district's paid counters are recomputed as assessments reach `PAID_OFF`.

For each assessment on installments — selected or defaulted — the amortization schedule is built. Take the final levy as principal, derive the annual rate from the district's `annual_interest_rate_bp` divided by ten thousand, and let the term be `term_years`. When the rate is zero, the level yearly amount is the levy divided by the number of years, rounded half-up to whole cents, and every year carries zero interest. Otherwise the level amount is the annuity figure — the levy times the annual rate, divided by one minus the quantity one-plus-rate raised to the negative power of the term — rounded half-up to whole cents exactly once and held fixed thereafter. The schedule walks the years in order against a running balance that starts at the levy: each year's interest is the current balance times the annual rate, rounded half-up to whole cents; in every year but the last, the payment is the level amount and the principal portion is the level amount minus that year's interest; in the final year, the principal portion is whatever balance remains and the payment is that balance plus the year's interest, so the balance reaches exactly zero by construction and the final year absorbs all rounding drift. Each year mints one annual invoice — `kind` set to `ANNUAL`, `year_index` running from 1 through the term, `due_date` set that many 365-day years after the true-up instant, `issue_date` thirty days before its own due date, `principal_cents` and `interest_cents` set to the year's components, and `penalty_cents` and `paid_cents` starting at zero — created in `SCHEDULED`. Every invoice also carries its `district_id`, denormalized from the assessment, and the `parcel_assessment_id` it belongs to. The assessment's `principal_balance_cents` is set to the full `final_levy_cents` and the assessment itself moves to `IN_REPAYMENT`. With deltas settled and schedules built, the district advances to `BILLING` and its `version` increments.

### 3.8. Payment Options, Collections, and the Delinquency Cycle

The thirty days following levy are the owner's election window. While the current time is on or before the district's `payment_option_deadline` — afterwards the window is shut and election attempts fail with `ERR_PAYMENT_OPTION_WINDOW_CLOSED` — the owner of the parcel behind an assessment selects `PREPAY_FULL` or `INSTALLMENTS` as their `option`. The assessment must be `LEVIED` (`ERR_ASSESSMENT_NOT_LEVIED`), the caller must own the underlying parcel (`ERR_NOT_RESOURCE_OWNER`), and the option may be chosen at most once (`ERR_ASSESSMENT_OPTION_ALREADY_SELECTED`). Choosing `INSTALLMENTS` requires a `term_years` of 5 or 10, while `PREPAY_FULL` forbids it outright; a missing, present-but-wrong, or misplaced term draws `ERR_TERM_NOT_ALLOWED`. A successful election stores the choice in `payment_option`, stamps `option_selected_at`, and advances the assessment's `version`.

A prepaying owner then posts a single payment equal to the cent to the assessment's `preliminary_amount_cents`; any other amount against a `LEVIED` assessment — or a prepay attempted without the `PREPAY_FULL` option in force — fails with `ERR_INVALID_PREPAY_AMOUNT`, and the same `ERR_PAYMENT_OPTION_WINDOW_CLOSED` window discipline applies. With the `PREPAY_FULL` option in force, however, the payoff-cap rule is evaluated before the exact-equality rule: a posted amount that exceeds the payoff quote computed at receipt time is rejected with `ERR_OVERPAYMENT` even though it also mismatches the preliminary amount. The full amount lands on principal: `total_paid_cents` accumulates it, `principal_balance_cents` falls to the preliminary amount minus the payment — zero, pending the true-up — and the assessment becomes `PREPAID` with its `version` advanced.

Ordinary collections follow one waterfall. A payment posts against a payable assessment — `LEVIED` on the prepay path above, or `SETTLEMENT_DUE`, `IN_REPAYMENT`, or `DELINQUENT` on the collection path; against any other status the posting is refused with `ERR_ASSESSMENT_NOT_LEVIED` — by the parcel's owner (`ERR_NOT_RESOURCE_OWNER`), carrying `parcel_assessment_id`, a strictly positive `amount_cents` (`ERR_INVALID_AMOUNT`), and a `method` of `CHECK`, `ACH`, or `CARD`. The amount may not exceed the payoff quote computed at receipt time; an excess is rejected with `ERR_OVERPAYMENT` (HTTP 402). Because every posted payment mutates balances and invoice allocations, the request must also carry `expected_parcel_assessment_version` equal to the assessment's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). Each accepted **Payment** is the append-only event of §2.5: it stamps `received_at` from the logical clock and the waterfall records how the money split across `applied_penalty_cents`, `applied_interest_cents`, and `applied_principal_cents`.

The waterfall order is pinned. Billed invoices are filled first, oldest `due_date` first with creation-time tie-breaks, and within each invoice the order is penalty, then interest, then principal; an invoice moves `ISSUED` → `PARTIALLY_PAID` → `PAID` as it fills — or `ISSUED` → `PAID` in one step when covered outright — with a partial payment against a `DELINQUENT` invoice likewise moving it to `PARTIALLY_PAID` (a later billing run may mark it delinquent again), and a `DELINQUENT` invoice that reaches `PAID` triggers the cure check: once no delinquent invoice of the assessment remains, the assessment itself returns from `DELINQUENT` to `IN_REPAYMENT`. Whatever then remains settles accrued-but-unbilled interest, and any final remainder prepays principal. When the principal balance reaches zero with nothing billed-and-unpaid and nothing accrued-and-unpaid outstanding, the assessment becomes `PAID_OFF`, its still-`SCHEDULED` future invoices are `VOIDED`, and the district's `paid_assessment_count`, `total_assessment_count`, and `all_assessments_paid` are recomputed — the last of these true exactly when at least one assessment exists outside `REMOVED` and `SUPERSEDED` and every such assessment is `PAID_OFF`. A payment that covers a supplemental invoice in full likewise moves a `SETTLEMENT_DUE` assessment to `PAID_OFF`, with the same counter recomputation. Every accepted payment advances the assessment's `version`.

Accrued interest, which feeds both the quote and the waterfall, runs simple actual/365 on outstanding principal: principal-change events — the true-up and each payment — are walked in chronological order with creation-time tie-breaks, and each segment contributes its balance times the annual rate times its day count divided by 365, rounded half-up to whole cents, the day count being the segment's exact elapsed time — elapsed seconds divided by 86,400, so fractional days count — and zero-length segments contributing nothing; the accrued-unpaid figure is the summed accrual less interest already paid, with the annual rate again derived from `annual_interest_rate_bp` divided by ten thousand. Assessments without a schedule — `PREPAID` or `SETTLEMENT_DUE` — accrue nothing: their accrued-unpaid figure is zero.

The payoff quote, available to the owning owner and to the `FinanceOfficer`, is a computed read reporting `payoff_cents` as the sum of `principal_balance_cents`, accrued-unpaid interest as of the quote instant, and unpaid penalty — the latter accumulated per delinquent invoice as whatever portion of its `penalty_cents` the waterfall has not yet covered, payments always filling penalty first. The response also carries `billed_unpaid_cents` — the unpaid principal, interest, and penalty across the `ISSUED`, `PARTIALLY_PAID`, and `DELINQUENT` invoices — plus `accrued_interest_cents`, `penalty_unpaid_cents`, and the `as_of` instant of the quote.

Collections are kept honest by the billing run, a `FinanceOfficer` operation available only while the district is in `BILLING` (`ERR_DISTRICT_NOT_IN_BILLING`). Each run sweeps the district's invoices: any `SCHEDULED` invoice whose `issue_date` has been reached becomes `ISSUED`; any `ISSUED` or `PARTIALLY_PAID` invoice whose grace period has fully elapsed — strictly later than thirty days past its `due_date`, so at exactly that thirty-day mark it remains undelinquent — becomes `DELINQUENT`, flipping its owning assessment from `IN_REPAYMENT` to `DELINQUENT` with it; and every delinquent invoice's `penalty_cents` is recomputed. Finally the run cures stragglers: any assessment still `DELINQUENT` with no `DELINQUENT` invoice remaining returns to `IN_REPAYMENT`. The run answers with `issued_count`, `newly_delinquent_count`, and `cured_count`, the last counting assessments the run returned to `IN_REPAYMENT`.

The penalty math depends on the district's `interest_method`. The overdue month count is the whole thirty-day months elapsed since the grace end and may be zero — an invoice can stand `DELINQUENT` with no penalty yet — and the unpaid base is the invoice's `principal_cents` plus `interest_cents` minus `paid_cents`; if that base is zero or negative, the penalty is zero. Under `SIMPLE`, the penalty is the overdue month count times one percent of that base, the one-percent figure rounded half-up to whole cents before multiplication. Under `COMPOUND`, the months are walked in sequence: each month's penalty is one percent of the running balance rounded half-up to whole cents, that penalty is added into the balance, and the invoice's penalty is the sum of the monthly steps — identical arrears and identical elapsed months therefore cost strictly more under compounding. Either way, `penalty_cents` is recomputed idempotently from the overdue month count at every run and never incremented piecemeal, so repeated runs at the same clock reading are no-ops.

Overpayments unwind through the credit mechanism. When a true-up has left money with the owner, a `FinanceOfficer` pays out against a positive `credit_balance_cents`; the requested `amount_cents` must be positive and no greater than the credit, failing with `ERR_REFUND_EXCEEDS_CREDIT` otherwise. A payout lowers `credit_balance_cents` and raises `total_refunded_cents` by the same figure and advances the assessment's `version`; the money identity is conserved at every step, with `total_paid_cents` minus `total_refunded_cents` always equal to `final_levy_cents` plus the remaining `credit_balance_cents`.

### 3.9. Terminal Outcomes: Acceptance and Abandonment

Final acceptance is the `CouncilPresident`'s last act on a district. It requires the district to be in `BILLING` (`ERR_DISTRICT_NOT_ACCEPTABLE`) and every assessment settled — `all_assessments_paid` must be true, meaning at least one assessment exists outside `REMOVED` and `SUPERSEDED` and all of them are `PAID_OFF`, with a shortfall rejected as `ERR_ASSESSMENTS_NOT_ALL_PAID`. Acceptance moves the district to `ACCEPTED` and increments its `version`.

Abandonment is the clerk's escape hatch, and it is only open early: from `DRAFT`, `PETITIONING`, `SCOPING`, `HEARING_SCHEDULED`, or `OBJECTION_WINDOW`. From any later status the district cannot be abandoned and the attempt fails with `ERR_DISTRICT_NOT_ABANDONABLE`. The cascade depends on where the district stood. From `DRAFT` there is nothing to unwind. From `PETITIONING`, the `CIRCULATING` petition is `VOIDED` and its `SUBMITTED` and `VERIFIED` signatures are `VOIDED` with it. From `SCOPING`, any `SUBMITTED` or `APPROVED` estimate becomes `SUPERSEDED`. From `HEARING_SCHEDULED`, the `SCHEDULED` hearing is `VOIDED` and the `PRELIMINARY` assessments are `SUPERSEDED`. From `OBJECTION_WINDOW`, the `HELD` hearing is `VOIDED`, the `PRELIMINARY` assessments are `SUPERSEDED`, and any objections still `FILED` or `UNDER_REVIEW` are `WITHDRAWN`. Every abandonment moves the district to `ABANDONED` and increments its `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or perform a computed read return `200 OK`. The table below is deliberately minimal: request payloads, response fields, and side effects are specified by the workflows of §3 and the global rules of §2, not repeated here. Endpoint paths match with or without a trailing slash. Rows marked "All roles" admit every one of the six declared roles; all endpoints still require the authentication headers of §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | SystemAdmin |
| POST | `/districts` | Create a special assessment district | CityClerk |
| GET | `/districts` | List districts (paginated; optional `status` filter) | All roles |
| GET | `/districts/{id}` | Get a district | All roles |
| POST | `/districts/{id}/abandon` | Abandon a district (early lifecycle states only) | CityClerk |
| POST | `/districts/{id}/close-objection-window` | Close the objection window and compute protest weight | CityClerk |
| POST | `/districts/{id}/complete-construction` | Move the district from construction to true-up | CityEngineer |
| POST | `/districts/{id}/finalize-true-up` | Compute final levies, settle prepaid deltas, build installment schedules | FinanceOfficer |
| POST | `/districts/{id}/billing-run` | Issue due invoices, mark delinquencies, accrue penalties, cure assessments | FinanceOfficer |
| POST | `/districts/{id}/accept` | Grant final acceptance when all assessments are paid off | CouncilPresident |
| GET | `/districts/{id}/parcels` | List parcels of a district (parcel_number ascending) | All roles |
| GET | `/districts/{id}/petitions` | List petitions of a district | All roles |
| GET | `/districts/{id}/cost-estimates` | List cost estimates of a district | SystemAdmin, CityClerk, CityEngineer, FinanceOfficer, CouncilPresident |
| GET | `/districts/{id}/parcel-assessments` | List parcel assessments of a district (parcel_number ascending; optional `status` filter) | All roles |
| GET | `/districts/{id}/hearings` | List hearings of a district | All roles |
| GET | `/districts/{id}/objections` | List objections of a district | All roles |
| GET | `/districts/{id}/resolutions` | List council resolutions of a district | SystemAdmin, CityClerk, CityEngineer, FinanceOfficer, CouncilPresident |
| GET | `/districts/{id}/construction-phases` | List construction phases of a district | SystemAdmin, CityClerk, CityEngineer, FinanceOfficer, CouncilPresident |
| GET | `/districts/{id}/change-orders` | List change orders of a district | SystemAdmin, CityClerk, CityEngineer, FinanceOfficer, CouncilPresident |
| GET | `/districts/{id}/invoices` | List invoices of a district (due_date ascending; optional `status` filter) | All roles |
| POST | `/owners` | Register a property owner | CityClerk |
| GET | `/owners` | List property owners (paginated) | SystemAdmin, CityClerk, CityEngineer, FinanceOfficer, CouncilPresident |
| GET | `/owners/{id}` | Get a property owner | All roles |
| GET | `/owners/{id}/parcels` | List parcels owned by an owner | All roles |
| GET | `/owners/{id}/signatures` | List petition signatures made by an owner | SystemAdmin, CityClerk, FinanceOfficer, CouncilPresident, PropertyOwner |
| GET | `/owners/{id}/objections` | List objections filed by an owner | SystemAdmin, CityClerk, FinanceOfficer, CouncilPresident, PropertyOwner |
| POST | `/parcels` | Add a parcel to a DRAFT district | CityClerk |
| GET | `/parcels` | List parcels (optional `district_id` and `owner_id` filters) | All roles |
| GET | `/parcels/{id}` | Get a parcel | All roles |
| GET | `/parcels/{id}/signatures` | List signatures recorded against a parcel | SystemAdmin, CityClerk, FinanceOfficer, CouncilPresident, PropertyOwner |
| GET | `/parcels/{id}/assessments` | List assessments of a parcel | All roles |
| GET | `/parcels/{id}/objections` | List objections filed against a parcel | SystemAdmin, CityClerk, FinanceOfficer, CouncilPresident, PropertyOwner |
| POST | `/petitions` | Open a petition for a DRAFT district | CityClerk |
| GET | `/petitions/{id}` | Get a petition | All roles |
| POST | `/petitions/{id}/close` | Close circulation and compute support | CityClerk |
| GET | `/petitions/{id}/signatures` | List signatures of a petition | SystemAdmin, CityClerk, FinanceOfficer, CouncilPresident, PropertyOwner |
| POST | `/signatures` | Property owner signs a circulating petition for their own parcel | PropertyOwner |
| GET | `/signatures/{id}` | Get a signature | SystemAdmin, CityClerk, FinanceOfficer, CouncilPresident, PropertyOwner |
| POST | `/signatures/{id}/verify` | Clerk verifies a submitted signature | CityClerk |
| POST | `/signatures/{id}/reject` | Clerk rejects a submitted signature with a reason | CityClerk |
| POST | `/signatures/{id}/withdraw` | Owner withdraws their signature while the petition circulates | PropertyOwner |
| POST | `/cost-estimates` | Engineer submits a cost estimate (OCC on district) | CityEngineer |
| GET | `/cost-estimates/{id}` | Get a cost estimate | SystemAdmin, CityClerk, CityEngineer, FinanceOfficer, CouncilPresident |
| POST | `/cost-estimates/{id}/approve` | Engineer approves a SUBMITTED estimate | CityEngineer |
| POST | `/hearings` | Schedule the public hearing; locks the estimate and computes the preliminary roll | CityClerk |
| GET | `/hearings/{id}` | Get a hearing | All roles |
| POST | `/hearings/{id}/record-held` | Record that the hearing was held; opens the objection window | CityClerk |
| GET | `/hearings/{id}/objections` | List objections filed on a hearing | SystemAdmin, CityClerk, FinanceOfficer, CouncilPresident, PropertyOwner |
| POST | `/objections` | Owner files an objection during the objection window | PropertyOwner |
| GET | `/objections/{id}` | Get an objection | All roles |
| POST | `/objections/{id}/start-review` | Clerk takes an objection under review | CityClerk |
| POST | `/objections/{id}/sustain` | Clerk sustains an objection: parcel and assessment removed, roll reallocated | CityClerk |
| POST | `/objections/{id}/overrule` | Clerk overrules an objection | CityClerk |
| POST | `/objections/{id}/withdraw` | Owner withdraws a FILED objection | PropertyOwner |
| POST | `/resolutions` | Record a council resolution (OCC on district) | CouncilPresident |
| GET | `/resolutions/{id}` | Get a resolution | SystemAdmin, CityClerk, CityEngineer, FinanceOfficer, CouncilPresident |
| GET | `/parcel-assessments/{id}` | Get a parcel assessment | All roles |
| POST | `/parcel-assessments/{id}/select-payment-option` | Owner selects PREPAY_FULL or INSTALLMENTS within 30 days of levy | PropertyOwner |
| POST | `/parcel-assessments/{id}/payoff-quote` | Computed read: payoff quote as of now | PropertyOwner, FinanceOfficer |
| POST | `/parcel-assessments/{id}/refund-credit` | Finance officer pays out an overpayment credit | FinanceOfficer |
| GET | `/parcel-assessments/{id}/invoices` | List invoices of an assessment (due_date ascending) | All roles |
| GET | `/parcel-assessments/{id}/payments` | List payments of an assessment | All roles |
| POST | `/construction-phases` | Plan a construction phase (season, crew, and capacity checks) | CityEngineer |
| GET | `/construction-phases/{id}` | Get a construction phase | SystemAdmin, CityClerk, CityEngineer, FinanceOfficer, CouncilPresident |
| POST | `/construction-phases/{id}/start` | Start a PLANNED phase on or after its start date | CityEngineer |
| POST | `/construction-phases/{id}/complete` | Complete an IN_PROGRESS phase | CityEngineer |
| POST | `/construction-phases/{id}/cancel` | Cancel a PLANNED phase | CityEngineer |
| GET | `/construction-phases/{id}/change-orders` | List change orders linked to a phase | SystemAdmin, CityClerk, CityEngineer, FinanceOfficer, CouncilPresident |
| POST | `/change-orders` | Engineer proposes a change order during construction | CityEngineer |
| GET | `/change-orders/{id}` | Get a change order | SystemAdmin, CityClerk, CityEngineer, FinanceOfficer, CouncilPresident |
| POST | `/change-orders/{id}/approve` | Approve a change order (must be a different engineer than the proposer) | CityEngineer |
| POST | `/change-orders/{id}/reject` | Reject a change order | CityEngineer |
| GET | `/invoices/{id}` | Get an invoice | All roles |
| POST | `/payments` | Owner posts a payment against their assessment (OCC on assessment) | PropertyOwner |
| GET | `/payments/{id}` | Get a payment event | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is only the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_OVERPAYMENT` | 402 Payment Required |
| `ERR_DISTRICT_NOT_FOUND` | 404 Not Found |
| `ERR_OWNER_NOT_FOUND` | 404 Not Found |
| `ERR_PARCEL_NOT_FOUND` | 404 Not Found |
| `ERR_PETITION_NOT_FOUND` | 404 Not Found |
| `ERR_SIGNATURE_NOT_FOUND` | 404 Not Found |
| `ERR_COST_ESTIMATE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_HEARING_NOT_FOUND` | 404 Not Found |
| `ERR_OBJECTION_NOT_FOUND` | 404 Not Found |
| `ERR_RESOLUTION_NOT_FOUND` | 404 Not Found |
| `ERR_PHASE_NOT_FOUND` | 404 Not Found |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DISTRICT_NOT_DRAFT` | 409 Conflict |
| `ERR_DISTRICT_NOT_IN_SCOPING` | 409 Conflict |
| `ERR_NO_APPROVED_ESTIMATE` | 409 Conflict |
| `ERR_DISTRICT_NOT_IN_OBJECTION_WINDOW` | 409 Conflict |
| `ERR_DISTRICT_NOT_IN_COUNCIL_REVIEW` | 409 Conflict |
| `ERR_DISTRICT_NOT_APPROVED_OR_UNDER_CONSTRUCTION` | 409 Conflict |
| `ERR_DISTRICT_NOT_IN_CONSTRUCTION` | 409 Conflict |
| `ERR_PHASES_NOT_ALL_COMPLETE` | 409 Conflict |
| `ERR_DISTRICT_NOT_IN_TRUE_UP` | 409 Conflict |
| `ERR_DISTRICT_NOT_IN_BILLING` | 409 Conflict |
| `ERR_DISTRICT_NOT_ACCEPTABLE` | 409 Conflict |
| `ERR_ASSESSMENTS_NOT_ALL_PAID` | 409 Conflict |
| `ERR_DISTRICT_NOT_ABANDONABLE` | 409 Conflict |
| `ERR_PETITION_NOT_CIRCULATING` | 409 Conflict |
| `ERR_SIGNATURE_NOT_VERIFIABLE` | 409 Conflict |
| `ERR_SIGNATURE_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_ESTIMATE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_HEARING_NOT_SCHEDULED` | 409 Conflict |
| `ERR_OBJECTION_NOT_FILED` | 409 Conflict |
| `ERR_OBJECTION_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_UNRESOLVED_OBJECTIONS` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_LEVIED` | 409 Conflict |
| `ERR_ASSESSMENT_OPTION_ALREADY_SELECTED` | 409 Conflict |
| `ERR_PHASE_NOT_PLANNED` | 409 Conflict |
| `ERR_PHASE_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_CHANGE_ORDER_NOT_PROPOSED` | 409 Conflict |
| `ERR_REMAND_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_HEARING_NOTICE_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_HEARING_DATE_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_OBJECTION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_OBJECTION_WINDOW_STILL_OPEN` | 422 Unprocessable Entity |
| `ERR_PAYMENT_OPTION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_SEASON_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PHASE_START_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_PARCEL_NOT_IN_DISTRICT` | 422 Unprocessable Entity |
| `ERR_PHASE_NOT_IN_DISTRICT` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PARCEL_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_OWNER_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_SIGNATURE` | 409 Conflict |
| `ERR_DUPLICATE_OBJECTION` | 409 Conflict |
| `ERR_INELIGIBLE_PARCEL` | 409 Conflict |
| `ERR_PHASE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_CONSTRUCTION_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_VENUE_DATE_CONFLICT` | 409 Conflict |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_INVALID_PREPAY_AMOUNT` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_CREDIT` | 422 Unprocessable Entity |
| `ERR_TERM_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_METHOD_NOT_ALLOWED` | 405 Method Not Allowed |
| `ERR_INTERNAL` | 500 Internal Server Error |
