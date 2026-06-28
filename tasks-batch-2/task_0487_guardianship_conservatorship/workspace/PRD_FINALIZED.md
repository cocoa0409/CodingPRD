# Guardianship & Conservatorship API — Product Requirements Document

## 1. Introduction

When a court is asked to strip an adult of the legal right to manage their own person or estate, the proceeding is among the most consequential a probate bench handles. A petition alleging incapacity sets in motion an adversarial, time-gated sequence: a judge must find probable cause, an independent examiner must evaluate capacity, the bench must adjudicate, a fiduciary must be appointed and bonded, an estate must be inventoried and protected behind a restricted account, every dollar of spending must be planned and (above a threshold) court-approved, and the fiduciary's stewardship must be re-proved through periodic accountings and court reviews until the case is either terminated or the protected person's capacity is restored. This API is the system of record for that lifecycle.

The system's central obligation is **integrity under segregation of duties**: the person who petitions may not evaluate capacity, the examiner who evaluates may not adjudicate, and the fiduciary who spends may not approve their own spending. Equally important is **fiscal conservatism** — a protected estate is held in a court-restricted account whose spendable balance is derived, never directly set, and every expenditure must fit simultaneously under a budgeted category cap and the account's available funds before money can move. A third concern is **temporal correctness**: accountings come due on a clock, care-plan coverage windows must tile a person's timeline without gaps overlapping, and reviews may only be held once their window opens. Because tests must be deterministic, the server runs on a logical clock rather than wall-clock time.

This document specifies the global contracts every endpoint shares (Section 2), the business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5). The structural model is deliberately flat: each of the fourteen resource types is its own top-level collection, and parent–child relationships travel as foreign keys in request bodies and are recovered through filtered list queries rather than nested URL paths.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under `/gc`, with the sole exception of the administrative clock endpoint described in Section 2.10.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly five roles, spelled precisely as follows: `Petitioner`, `CourtExaminer`, `Judge`, `Fiduciary`, and `CourtClerk`. When a request is authenticated but the acting role is not permitted to invoke the requested operation, the system responds with `ERR_FORBIDDEN_ROLE`.

These roles are segregated by design. A `Petitioner` files the petition that opens proceedings and may register subjects, candidate fiduciaries, and cases, but may never evaluate capacity or rule on a petition. A `CourtExaminer` authors and files the capacity evaluation but may neither file the petition nor adjudicate it. A `Judge` holds all adjudicative and approval power — probable cause, ordering evaluations, granting and dismissing, the entire appointment lifecycle, bond, inventory, budget, expenditure and accounting approvals, opening and closing reviews, termination and restoration, and the holding and disposing of reviews — but may never file a petition or author an evaluation. A `Fiduciary` is the appointed (or candidate) guardian or conservator who submits operational artifacts but cannot approve them. A `CourtClerk` is the administrative operator who drives the logical clock, registers persons and fiduciaries, opens cases and restricted accounts, and schedules reviews, with no adjudicative power. All five roles may invoke the read (GET) endpoints on every resource.

Four of the five roles carry an **opaque** identity: when `X-User-Role` is `Petitioner`, `CourtExaminer`, `Judge`, or `CourtClerk`, the value of `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server may record such an identifier where a workflow calls for it — for example, the `petitioner_user_id` written onto a `Petition` at filing time, or the `examiner_user_id` written onto a `CapacityEvaluation` at authoring time — but it never compares that identifier to any entity's `id`. By contrast, the `Fiduciary` role is **entity-backed**: when `X-User-Role` is `Fiduciary`, the `X-User-ID` is the `id` of the acting `Fiduciary` entity. The recorded operator identifiers do matter for segregation-of-duties checks: the examiner filing an evaluation must not be the same user as the petition's `petitioner_user_id`, and the judge granting or dismissing a petition must not be that same petitioner; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped from the front of the result and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Flat Topology

Every resource carries a system-minted `id` formatted as a UUID, with no type prefix. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created. All fourteen entity types in this system additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and a `version` integer that begins at its initial value and increments by one on each mutation. The `version` integer is the basis for the optimistic-concurrency mechanism described in Section 2.8.

There are no nested URL paths in this API. Each resource type is its own collection under `/gc`, and a child resource references its parent through a foreign-key field carried in the creation body — for example a `Petition` carries a `case_id`, an `Appointment` carries a `case_id` and a `fiduciary_id`, a `Bond` carries an `appointment_id`. To recover the children of a parent (reverse reachability), the corresponding list endpoint accepts the foreign-key field as an optional query parameter. Path identifiers are still validated left-to-right: when an operation addresses a resource by its `id` in the path and that resource does not exist, the request is rejected with `ERR_NOT_FOUND` before any body-level foreign key is considered. Once path identifiers resolve, body foreign keys — among them `protected_person_id`, `nominated_fiduciary_id`, `case_id`, `petition_id`, `appointment_id`, `fiduciary_id`, `budget_id`, and `subject_ref_id` — are resolved next; a body foreign key that does not exist, or that resolves to a resource outside the case scope it is required to belong to, is rejected with `ERR_REFERENCE_NOT_FOUND`.

### 2.5. Monetary Values and Precision

All monetary quantities in this system are integer counts of cents; they are never fractional. Aggregations (running ledgers, category spend, account balances) are exact integer arithmetic with no rounding. The two places where a non-integer intermediate arises — the statutory fiduciary fee and the surety bond penal sum — apply the **round half up** rule to reach a whole number of cents, and Section 3 specifies precisely at which step in each calculation the rounding is performed, because the order of rounding is observable in the result.

### 2.6. Derived Fields and Hierarchical Consistency

Several fields are **computed** and may never be supplied by a client: a `ProtectedPerson`'s `capacity_status` (one of `PRESUMED_COMPETENT`, `ADJUDICATED_INCAPACITATED`, `RESTORED`) and `active_case_id`; a `Fiduciary`'s `is_disqualified` and `open_appointment_count`; a `GuardianshipCase`'s `status`, `protection_posture`, `requires_bond`, `next_accounting_due_iso`, and `overdue_accounting_count`; the `status` field of every entity that has one; an `Appointment`'s `granted_authority` and `letters_issued_iso`; a `Bond`'s `required_amount_cents`; a `RestrictedAccount`'s `principal_balance_cents`, `encumbered_cents`, and `available_balance_cents`; an `Inventory`'s `total_estate_cents`; a `Budget`'s `care_spent_cents`, `medical_spent_cents`, and `admin_spent_cents`; an `Expenditure`'s `requires_court_approval` and `disbursed_at`; and an `AccountingReport`'s `ledger_disbursed_cents`, `projected_disbursed_cents`, `variance_cents`, and `fiduciary_fee_cents`.

A single operation frequently mutates more than one resource. When the system changes a child in a way that bears on a parent's state — an appointment qualifying, an expenditure encumbering funds, an accounting being approved — the parent is mutated too: its `updated_at` is refreshed and its `version` is incremented. The `GuardianshipCase` is the aggregate root, and its `status` and `protection_posture` are re-derived whenever a relevant child changes (Section 3 details each cascade). Some transitions are not driven by an explicit client call on the affected resource at all: a petition advances by itself when its evaluation is filed, a budget is superseded the moment a newer one for the same year is approved, a case activates the moment its appointment qualifies, and a care plan is treated as expired the moment the clock passes its window end. These automatic transitions are computed by the server as part of the triggering operation or re-derived on read.

### 2.7. Case Protection Posture

Every `GuardianshipCase` carries a derived gate field, `protection_posture`, valued `GREEN`, `AMBER`, or `RED`, recomputed on any change to the case's appointments, expenditures, accountings, or restricted account, and on any clock advance that affects due dates. The posture is decided by a strict precedence in which `RED` dominates `AMBER`, which dominates `GREEN`.

The recomputation first refreshes the case's `overdue_accounting_count`. That count is 1 when the case is in `ACTIVE` or `UNDER_REVIEW` status, the logical clock has reached or passed the case's `next_accounting_due_iso`, and no `AccountingReport` for the current period is in `SUBMITTED` or `APPROVED` status; otherwise it is 0. The posture is then `RED` if either the case is `ACTIVE` but has no `Appointment` in `ACTIVE` status, or the `overdue_accounting_count` is at least 2. Failing those `RED` conditions, the posture is `AMBER` if any one of these holds: the `overdue_accounting_count` equals 1, the restricted account's `available_balance_cents` is below zero, or any `Appointment` on the case is in `SUSPENDED` status. If none of the `RED` or `AMBER` conditions hold, the posture is `GREEN`.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded against stale reads of the aggregate root by an optimistic-concurrency check on the `GuardianshipCase`'s `version`. Both operations require the caller to supply `expected_case_version` as a non-optional field carrying the case `version` the client last observed; if that value does not equal the case's current `version`, the operation is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412).

The first guarded operation is creating an `Expenditure`. A prior write may have legitimately changed the case's spendable restricted balance since the client last read it — another expenditure reaching `APPROVED` and encumbering funds, an accounting approval crediting income, or an appointment suspension freezing the account — so a charge derived against a superseded view must be re-derived against the advanced `version` rather than admitted. The second guarded operation is approving a `Budget`. Another budget for the same period may have just been approved (which would supersede the one being approved), so the approver's view of the governing budget may be stale and must be re-derived against the advanced case `version`. No other endpoint takes a version field. Both of these write operations, when they succeed, increment the case's `version` by one.

### 2.9. Estate Funds and the Restricted Account

The protected estate's liquid funds live in a `RestrictedAccount` whose spendable figure is derived, never set directly. The account's `available_balance_cents` is always its `principal_balance_cents` minus its `encumbered_cents`. The principal is the running total of credits minus debits: it is credited by the liquid assets funded when an inventory is approved and by the reported income credited when an accounting is approved, and it is debited by the amounts of expenditures that reach `DISBURSED`. The encumbered figure is the sum of expenditure amounts that are `APPROVED` but not yet `DISBURSED` — funds held against the account but not yet paid out. This construction holds a conservation invariant: as an expenditure moves `REQUESTED → APPROVED → DISBURSED`, approval raises encumbered by the amount, and disbursement simultaneously lowers encumbered by the amount and lowers principal by the same amount, so the available balance nets down by exactly the expenditure amount across the pair and never drifts. The account's `status` is `OPEN`, `FROZEN`, or `CLOSED`; a `FROZEN` account blocks disbursement, and the account is `CLOSED` when its case terminates.

### 2.10. The Logical Clock

The server keeps a logical clock rather than reading wall-clock time. Before any clock-setting call the clock reads exactly `2026-01-01T00:00:00Z`, the startup default, and the server never falls back to real time. A `CourtClerk` may advance the clock to an arbitrary UTC instant by supplying a `to_iso8601` value; the response reports the new instant as `now_iso`. Advancing the clock re-derives every time-gated determination against the new instant: care plans whose window has closed are treated as expired, and overdue-accounting evaluations (and therefore protection posture) are recomputed.

## 3. Business Logic & Workflows

### 3.1. Opening a Case: Subjects, Fiduciaries, and the Petition

Two reference entities exist before any case. A protected person — the alleged-incapacitated subject — is registered with a `full_name`, a `date_of_birth` given as an ISO date, and two figures that will later drive bond sizing: `annual_income_cents` (documented gross annual income, which must be zero or greater) and `liquid_estate_cents` (liquid personal property value at intake, also zero or greater). A newly registered person begins life with `capacity_status` of `PRESUMED_COMPETENT` and a null `active_case_id`. A candidate fiduciary is registered with a `full_name` and a `fiduciary_kind` of `FAMILY`, `PROFESSIONAL`, or `PUBLIC_AGENCY` — the kind selects the fee schedule later. A fresh fiduciary starts with `is_disqualified` false and `open_appointment_count` of zero.

Opening a case ties a subject to a proceeding. A case is created with a `protected_person_id` and a `case_type` of `GUARDIANSHIP` (authority over the person), `CONSERVATORSHIP` (authority over the estate), or `PLENARY` (both). The new case begins in `DRAFT` status with a `GREEN` posture. The system derives `requires_bond` as true exactly when the `case_type` is `CONSERVATORSHIP` or `PLENARY`, since those seek estate authority. Crucially, a protected person may have only one active proceeding at a time: opening a case sets the person's `active_case_id` to the new case, and an attempt to open a second case for a person whose `active_case_id` is already set is rejected with `ERR_PERSON_HAS_ACTIVE_CASE`.

The petition is what actually opens proceedings, and only a `Petitioner` may file one. A petition is filed against a case (`case_id`), nominates a candidate fiduciary (`nominated_fiduciary_id`), states the scope of authority sought in `requested_authority` (`PERSON`, `ESTATE`, or `BOTH`), and carries a free-text `alleged_grounds` statement of the alleged incapacity. On filing, the petition enters `FILED` and the filing operator's identifier is captured as `petitioner_user_id` for the segregation-of-duties checks that follow. A petition's lifecycle runs `FILED`, `PROBABLE_CAUSE`, `EVALUATION_ORDERED`, `READY_FOR_HEARING`, and then forks to either `GRANTED` or `DISMISSED`.

### 3.2. Probable Cause, Capacity Evaluation, and Adjudication

A judge moves a petition forward. Finding probable cause advances a petition from `FILED` to `PROBABLE_CAUSE` and, as a side effect, advances the parent case from `DRAFT` to `PENDING_EVALUATION`; the petition must be in `FILED` or the request is rejected with `ERR_INVALID_STATE`. Ordering an evaluation advances the petition from `PROBABLE_CAUSE` to `EVALUATION_ORDERED` and requires the petition to be in `PROBABLE_CAUSE`, again under `ERR_INVALID_STATE` otherwise.

Capacity is evaluated by an independent examiner. A `CourtExaminer` drafts a `CapacityEvaluation` against a petition (`petition_id`), recording a `finding` of `INCAPACITATED`, `PARTIALLY_INCAPACITATED`, or `COMPETENT`, and a `recommended_scope` — the least-restrictive scope the examiner recommends — of `NONE`, `PERSON`, `ESTATE`, or `BOTH`. The evaluation begins in `DRAFT`, and the authoring operator is captured as `examiner_user_id`. Filing the evaluation locks it, transitioning it from `DRAFT` to `FILED`. Filing has three preconditions evaluated against the same `ERR_INVALID_STATE`/specific-error discipline used elsewhere: the evaluation must be in `DRAFT` (else `ERR_INVALID_STATE`), the parent petition must be in `EVALUATION_ORDERED` (else `ERR_EVALUATION_NOT_ORDERED`), and the `examiner_user_id` must differ from the parent petition's `petitioner_user_id` (else `ERR_SEGREGATION_OF_DUTIES`). When an evaluation is filed, its parent petition automatically bubbles up from `EVALUATION_ORDERED` to `READY_FOR_HEARING`; the petition is never advanced to `READY_FOR_HEARING` by a direct call.

Adjudication is the fork. Granting a petition requires it to be in `READY_FOR_HEARING` (else `ERR_INVALID_STATE`). Three further conditions guard the grant: the granting judge's `X-User-ID` must differ from the petition's `petitioner_user_id` (else `ERR_SEGREGATION_OF_DUTIES`); the petition's filed evaluation `finding` must not be `COMPETENT` (else `ERR_EVALUATION_FINDS_COMPETENT`); and the petition's `requested_authority` must be covered by the evaluation's `recommended_scope` (else `ERR_SCOPE_EXCEEDS_RECOMMENDATION`). Coverage follows the ordering in which `BOTH` covers everything, `PERSON` and `ESTATE` each cover themselves and `NONE`, and `NONE` covers only `NONE`; in other words an authority is covered only when the recommended scope is `BOTH`, or equals the requested authority, with `NONE` never covering `PERSON`, `ESTATE`, or `BOTH`. A successful grant moves the petition to `GRANTED`, advances the case from `PENDING_EVALUATION` to `AWAITING_APPOINTMENT`, and sets the protected person's `capacity_status` to `ADJUDICATED_INCAPACITATED`.

Dismissal ends the proceeding without protection. A judge may dismiss a petition from either `READY_FOR_HEARING` or `PROBABLE_CAUSE` (any other from-state yields `ERR_INVALID_STATE`), and in both cases the dismissing judge must not be the petition's `petitioner_user_id` (else `ERR_SEGREGATION_OF_DUTIES`). Dismissal moves the petition to `DISMISSED`, drives the case to `TERMINATED` (no protection was ordered), and clears the protected person's `active_case_id` back to null.

### 3.3. Appointment, Bond, and Qualification

Once a case is `AWAITING_APPOINTMENT`, a judge creates the appointment that will receive letters. An appointment is created with a `case_id` and a `fiduciary_id`. Its `granted_authority` — `PERSON`, `ESTATE`, or `BOTH` — is copied by the system from the granted petition's `requested_authority` and may not be supplied by the client. The appointment begins in `PENDING_QUALIFICATION` with a null `letters_issued_iso`. The nominated fiduciary must not be disqualified at creation: if the `Fiduciary`'s `is_disqualified` flag is true, the create is rejected with `ERR_FIDUCIARY_DISQUALIFIED`. When the case `requires_bond`, creating the appointment also creates a `Bond` in `REQUIRED` status whose `required_amount_cents` is computed by the bond-sizing rule below.

The surety bond protects the estate before an estate-authority fiduciary may act. A bond references its `appointment_id` and records the `surety_name` and a `posted_amount_cents` (the penal sum the surety actually posts, which begins at zero and must be zero or greater). The court-required penal sum, `required_amount_cents`, is derived at bond creation from the protected person's `liquid_estate_cents` and `annual_income_cents` together with the case's `case_type`. The derivation works in cents throughout: take the exposure as the sum of the liquid estate and one year of income; buffer the first 10,000,000 cents of that exposure at a multiplier of one and any exposure above 10,000,000 cents at a multiplier of one-and-one-tenth; add the two buffered slices to obtain a raw figure. If the case is `PLENARY`, add a reserve of 1,000,000 cents to the raw figure. Round the raw figure half up to a whole number of cents, then take the greater of that rounded figure and a floor of 500,000 cents — the floor wins whenever the buffered exposure would otherwise fall below it. The result is the `required_amount_cents`.

A fiduciary posts the bond by supplying `posted_amount_cents` and `surety_name`; posting advances the bond from `REQUIRED` to `POSTED` and requires that the posted amount be at least the `required_amount_cents` (else `ERR_BOND_INSUFFICIENT`) and that the bond be in `REQUIRED` (else `ERR_INVALID_STATE`). A judge then approves the posted bond, moving it from `POSTED` to `APPROVED`, or rejects it, moving it from `POSTED` back to `REQUIRED` and resetting `posted_amount_cents` to zero so the fiduciary must post afresh; both require the bond to be in `POSTED`.

Qualification activates the appointment and, with it, the case. A judge qualifies an appointment that is in `PENDING_QUALIFICATION` while the case is in `AWAITING_APPOINTMENT` (either condition failing yields `ERR_INVALID_STATE`); the fiduciary must not be disqualified (else `ERR_FIDUCIARY_DISQUALIFIED`); and if the case `requires_bond`, the appointment's bond must be in `APPROVED` (else `ERR_BOND_NOT_APPROVED`). Qualification stamps `letters_issued_iso` with the current clock instant, moves the appointment to `ACTIVE`, increments the fiduciary's `open_appointment_count` by one, and bubbles the case up from `AWAITING_APPOINTMENT` to `ACTIVE`. At that moment the case's `next_accounting_due_iso` is set to the letters-issued instant advanced by one standard accounting period (the fixed `ACCOUNTING_PERIOD_DAYS` interval used throughout for accounting due dates).

A judge may suspend an `ACTIVE` appointment, moving it to `SUSPENDED` and freezing every `OPEN` restricted account on the case to `FROZEN` so disbursement is blocked while the fiduciary is suspended. Reinstating a `SUSPENDED` appointment returns it to `ACTIVE` and unfreezes every `FROZEN` account on the case back to `OPEN`. Removing an appointment is permitted from either `ACTIVE` or `SUSPENDED` (any other state yields `ERR_INVALID_STATE`); removal carries a `for_cause` flag, and when `for_cause` is true the fiduciary's `is_disqualified` flag is set true, barring future appointments. Removal moves the appointment to `REVOKED`, decrements the fiduciary's `open_appointment_count` by one (a suspended appointment still counts as open, so the decrement applies whether it was removed from `ACTIVE` or `SUSPENDED`), and, if the appointment's bond was `APPROVED`, exonerates it to `EXONERATED`.

### 3.4. The Estate: Inventory and the Restricted Account

A `CourtClerk` or a `Fiduciary` opens the court-restricted account that will hold the estate's funds, supplying the `case_id` and the depository's `institution_name`. The account opens in `OPEN` status with `principal_balance_cents`, `encumbered_cents`, and `available_balance_cents` all zero. The balance arithmetic and the conservation invariant are specified in Section 2.9.

The fiduciary swears an inventory of the estate, supplying the `case_id` and three appraised figures, each in cents and each zero or greater: `real_property_cents`, `liquid_assets_cents`, and `tangible_property_cents`. The system computes `total_estate_cents` as the sum of those three figures. The inventory begins in `DRAFT`. The fiduciary files the inventory, moving it from `DRAFT` to `FILED`, which requires the inventory to be in `DRAFT` (else `ERR_INVALID_STATE`) and the case to be `ACTIVE` (else `ERR_CASE_NOT_ACTIVE`). A judge then approves a `FILED` inventory, moving it to `APPROVED`; approval requires an `OPEN` restricted account to exist on the case (else `ERR_NO_RESTRICTED_ACCOUNT`). On approval, the inventory's `liquid_assets_cents` is credited into the account's `principal_balance_cents`, and the available balance is recomputed accordingly.

### 3.5. Budgeting and the Approval Gate

Spending must be planned. A fiduciary drafts an annual `Budget` for a case, supplying the `case_id`, the `period_year` the budget governs, and three per-category caps in cents, each zero or greater: `care_cap_cents`, `medical_cap_cents`, and `admin_cap_cents`. The budget begins in `DRAFT` with `care_spent_cents`, `medical_spent_cents`, and `admin_spent_cents` all zero; each spent counter accumulates the amounts of `DISBURSED` expenditures charged to that budget in that category. The fiduciary submits a `DRAFT` budget, moving it to `SUBMITTED`.

A judge approves a `SUBMITTED` budget. Approval requires the budget to be in `SUBMITTED` (else `ERR_INVALID_STATE`) and the case to be `ACTIVE` (else `ERR_CASE_NOT_ACTIVE`), and it is guarded by the optimistic-concurrency check of Section 2.8: the request must carry `expected_case_version` equal to the case's current `version`, or the approval is rejected with `ERR_STALE_CASE_VERSION`. A successful approval moves the budget to `APPROVED`, supersedes any other `APPROVED` budget on the same case for the same `period_year` to `SUPERSEDED` (only one approved budget governs a given year), and increments the case's `version` by one. Only an `APPROVED` budget governs spending; budgets in `DRAFT`, `SUBMITTED`, or `SUPERSEDED` govern nothing.

### 3.6. Expenditures: Routing, Approval, and Disbursement

A fiduciary requests a disbursement by creating an `Expenditure` with the `case_id`, the governing `budget_id`, a `category` of `CARE`, `MEDICAL`, or `ADMIN`, an `amount_cents` (which must be strictly greater than zero), a `payee_name`, and — because this is an OCC-guarded write per Section 2.8 — `expected_case_version`. On creation the system computes `requires_court_approval` and routes the expenditure accordingly, then increments the case's `version` by one.

The routing rule is a threshold with a deliberately strict boundary. An expenditure requires court approval when its `amount_cents` is strictly greater than the court-approval threshold of 1,000,000 cents, or when its `category` is `ADMIN`. An amount exactly equal to 1,000,000 cents in a non-`ADMIN` category does not require court approval: an amount of 1,000,000 cents routes on the auto-approval path, while 1,000,001 cents routes to court. When `requires_court_approval` is false the expenditure is auto-approved at creation, moving directly from `REQUESTED` to `APPROVED`; when it is true the expenditure is parked at `PENDING_COURT` for a judge.

Reaching `APPROVED` — whether automatically at creation or by a judge approving a `PENDING_COURT` expenditure — is gated by two fiscal checks. First the budget category cap: let the governing budget be the `APPROVED` budget referenced by `budget_id`; the approval is allowed only when the already-disbursed spend in this category (the budget's `{category}_spent_cents`) plus the outstanding holds in this category (the summed `amount_cents` of sibling expenditures on the same case and same budget in the same category that are currently `APPROVED`) plus this expenditure's own `amount_cents` does not exceed the category cap. The boundary is strict the other way: a total exactly equal to the cap is allowed, and only a total strictly greater than the cap is rejected, with `ERR_BUDGET_CAP_EXCEEDED`. Second the funds check: the restricted account's `available_balance_cents` must be at least this expenditure's `amount_cents`, or the approval is rejected with `ERR_INSUFFICIENT_RESTRICTED_FUNDS`. When both checks pass, reaching `APPROVED` raises the account's `encumbered_cents` by the amount and recomputes the available balance. A judge may instead deny a `PENDING_COURT` expenditure, moving it to `DENIED` with no balance effect.

Disbursement pays the money. A fiduciary disburses an `APPROVED` expenditure (else `ERR_INVALID_STATE`), which requires the restricted account to be `OPEN` (else `ERR_ACCOUNT_FROZEN`). Disbursement stamps `disbursed_at` with the current clock instant, moves the expenditure to `DISBURSED`, lowers `encumbered_cents` by the amount and lowers `principal_balance_cents` by the same amount (so the available balance is unchanged across this step), and adds the amount to the governing budget's spent counter for the expenditure's category. A judge may also deny an already-`APPROVED` expenditure; doing so moves it to `DENIED` and releases the hold, lowering `encumbered_cents` by the amount and recomputing the available balance. The `disbursed_at` instant is what buckets an expenditure into an accounting period.

### 3.7. Periodic Accounting and Dual-Variant Reconciliation

A fiduciary periodically proves stewardship through an `AccountingReport`, created with the `case_id`, the `period_year` it covers, and three sworn figures in cents, each zero or greater: `opening_balance_cents` (the sworn opening principal at period start), `reported_income_cents` (income received during the period), and `reported_disbursed_cents` (the disbursements the fiduciary reports for the period). The report begins in `DRAFT`. Submitting it moves it from `DRAFT` to `SUBMITTED` and requires the case to be in either `ACTIVE` or `UNDER_REVIEW` status (else `ERR_CASE_NOT_ACTIVE`). Submission recomputes four derived figures, and a later resubmission recomputes the same four after applying any corrected fields.

The first two derived figures are a deliberate pair of independent readings of the same period. The **chronological-actual** figure, `ledger_disbursed_cents`, is the audited truth: it is the sum of the `amount_cents` of every expenditure on this case that is in `DISBURSED` status and whose `disbursed_at` falls in the report's `period_year`. The running ledger is built in ascending order of `disbursed_at`, with `created_at` breaking ties (never the `id`), so the trace is deterministic. The **forward-looking** figure, `projected_disbursed_cents`, ignores actual disbursements entirely and reads the plan instead: it is zero when no `APPROVED` budget exists on the case for the report's `period_year`, and otherwise it is the sum of that single approved budget's `care_cap_cents`, `medical_cap_cents`, and `admin_cap_cents`. The two figures diverge whenever actual spend departs from plan. The `variance_cents` is then computed as the report's `reported_disbursed_cents` minus the chronological-actual `ledger_disbursed_cents`.

The third derived figure is the `fiduciary_fee_cents`, the fiduciary's commission for the period, which is itself a dual-variant calculation. Begin with a managed base equal to `opening_balance_cents` plus `reported_income_cents`. A marginal tiered schedule then applies to slices of that base across three bands. The first band is the portion of the base up to 4,999,990 cents and is charged at a rate of five percent. The second band is the portion of the base above 4,999,990 cents and up to 19,999,990 cents and is charged at four percent. The third band is the portion of the base above 19,999,990 cents and is charged at three percent. Crucially, each band's charge is rounded half up to a whole number of cents *individually*, and only then are the three rounded band charges summed — the rounding happens per band, before the summation, not on the grand total. This statutory figure is then subject to the fiduciary's kind: when the appointed fiduciary's `fiduciary_kind` is `FAMILY` or `PROFESSIONAL`, the `fiduciary_fee_cents` is exactly the statutory figure; when it is `PUBLIC_AGENCY`, the `fiduciary_fee_cents` is the lesser of the statutory figure and a public-agency cap of 300,000 cents, so a public-agency fee diverges from the statutory figure once the statutory figure exceeds the cap.

The report has a revision cycle. A judge may return a `SUBMITTED` report for correction, moving it to `RETURNED_FOR_CORRECTION`; the fiduciary resubmits a `RETURNED_FOR_CORRECTION` report, which may carry corrected `reported_disbursed_cents`, `reported_income_cents`, or `opening_balance_cents`, moves it back to `SUBMITTED`, and recomputes the ledger, projection, variance, and fee. A judge approves a `SUBMITTED` report only when the absolute value of its `variance_cents` is within the variance tolerance of 500 cents — that is, the variance's magnitude must be at most 500 cents, and a magnitude beyond that is rejected with `ERR_ACCOUNTING_VARIANCE`. Approval moves the report to `APPROVED`, advances the case's `next_accounting_due_iso` by one standard accounting period (the same fixed `ACCOUNTING_PERIOD_DAYS` interval applied at qualification), recomputes the case's `overdue_accounting_count`, credits the report's `reported_income_cents` into the restricted account's `principal_balance_cents` once and recomputes the available balance, and recomputes the case's protection posture.

### 3.8. Care Planning and the Coverage Timeline

For a case carrying authority over the person, the fiduciary maintains a visitation and care plan. A `CarePlan` is created with the `case_id`, a `residence_type` of `HOME`, `ASSISTED_LIVING`, `NURSING_FACILITY`, or `HOSPITAL`, a `visitation_min_per_month` (the minimum in-person visits per month the fiduciary commits to, zero or greater), and a coverage window expressed as `window_start_iso` (an inclusive lower bound) and `window_end_iso` (an exclusive upper bound). The plan begins in `DRAFT`.

Activating a plan moves it from `DRAFT` to `ACTIVE` and enforces the timeline discipline. The case must be `ACTIVE` (else `ERR_CASE_NOT_ACTIVE`); the window must be well-formed with `window_start_iso` strictly before `window_end_iso` (else `ERR_INVALID_WINDOW`); and the half-open window from `window_start_iso` up to but not including `window_end_iso` must not overlap the window of any other `ACTIVE` care plan on the same case (else `ERR_CARE_PLAN_OVERLAP`). Because the upper bound is exclusive, one plan ending exactly when another begins is not an overlap. A fiduciary may mark an `ACTIVE` plan `REPLACED`, which frees its window for a successor plan. A plan is treated as `EXPIRED` once the logical clock reaches or passes its `window_end_iso`; this is re-derived on read and on operations rather than driven by a client call.

### 3.9. Court Review, Termination, and Restoration

A case under scrutiny is moved into review. A judge opens a review on an `ACTIVE` case, moving its `status` to `UNDER_REVIEW` (the case must be `ACTIVE`, else `ERR_INVALID_STATE`), and closes a review to return an `UNDER_REVIEW` case to `ACTIVE` — but closing is refused while any `CourtReview` on the case remains in `SCHEDULED` or `HELD` status, with `ERR_OPEN_REVIEW_PENDING`.

A `CourtReview` is a periodic status report over a polymorphic subject. It is scheduled by a judge or clerk with the `case_id`, a `subject_kind` of `ACCOUNTING` or `CARE_PLAN`, a `subject_ref_id` naming the `AccountingReport` or `CarePlan` under review (resolved according to `subject_kind` and required to belong to the same case), and a review window given as `review_window_start_iso` (inclusive lower bound) and `review_window_end_iso` (exclusive upper bound). A review opens in `SCHEDULED` status with a `PENDING` `outcome`. A judge holds a `SCHEDULED` review, moving it to `HELD`, which requires the case to be `UNDER_REVIEW` (else `ERR_CASE_NOT_UNDER_REVIEW`) and the clock to have reached or passed `review_window_start_iso` (else `ERR_REVIEW_WINDOW_NOT_OPEN`). A judge disposes a `HELD` review, moving it to `CLOSED` and setting its `outcome` from the request to `ACCEPTED`, `CONTINUED`, or `SANCTIONED` (a missing or out-of-set outcome yields `ERR_INVALID_REQUEST`). Disposition carries one cross-entity side effect: when the outcome is `SANCTIONED`, the subject kind is `ACCOUNTING`, and the subject `AccountingReport` is currently `SUBMITTED`, that report is driven to `RETURNED_FOR_CORRECTION`.

Termination ends a case. A judge terminates a case that is in `ACTIVE` or `UNDER_REVIEW` (any other from-state yields `ERR_INVALID_STATE`), subject to two guards: no `Expenditure` on the case may be in `PENDING_COURT` or `APPROVED` status (else `ERR_PENDING_EXPENDITURES`), and if any `AccountingReport` exists, the one with the greatest `period_year` must be `APPROVED` (else `ERR_ACCOUNTING_OUTSTANDING`). Termination moves the case to `TERMINATED` and runs a cascade: every `ACTIVE` or `SUSPENDED` appointment on the case is revoked to `REVOKED`; each appointment that was `ACTIVE` decrements its fiduciary's `open_appointment_count` by one; each such appointment's `APPROVED` bond is exonerated to `EXONERATED`; every `OPEN` or `FROZEN` restricted account on the case is closed to `CLOSED`; and the protected person's `active_case_id` is cleared to null. The person's `capacity_status` is unchanged by termination and remains `ADJUDICATED_INCAPACITATED`.

Restoration is the gentler ending. A judge restores a case only from `UNDER_REVIEW` (else `ERR_INVALID_STATE`), and only when a `CourtReview` on the case has an `outcome` of `ACCEPTED` and a `status` of `CLOSED` (else `ERR_RESTORATION_NOT_REVIEWED`) and no `Expenditure` on the case is in `PENDING_COURT` or `APPROVED` (else `ERR_PENDING_EXPENDITURES`). Restoration moves the case to `RESTORED` and runs the same revoke-and-close cascade as termination — appointments to `REVOKED` with the matching `open_appointment_count` decrements, approved bonds to `EXONERATED`, accounts to `CLOSED`, and the person's `active_case_id` cleared to null — but differs in one respect: the protected person's `capacity_status` is set to `RESTORED` rather than left unchanged.

A note on validation ordering, since several checks can apply to one request. The system always evaluates them in a fixed priority: authentication first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of path-referenced resources (`ERR_NOT_FOUND`), then resolution of body foreign keys and their case scope (`ERR_REFERENCE_NOT_FOUND`), then request well-formedness — required fields present, correct types, enum values within their allowed sets, and amounts within their declared bounds such as `amount_cents` strictly above zero and caps at or above zero (`ERR_INVALID_REQUEST`), then the care-plan window check (`ERR_INVALID_WINDOW`), then the optimistic-concurrency check on the case version (`ERR_STALE_CASE_VERSION`), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then the from-state validity of the requested transition (`ERR_INVALID_STATE`), and only then the remaining business guards — case uniqueness, evaluation-ordered, competent-finding, scope, disqualification, bond, restricted-account existence, care-plan overlap, budget cap, funds, and accounting variance. This ordering means, for example, that a request from an unauthorized role is rejected for the role before any state check runs, and that a stale case version surfaces before a segregation-of-duties or state conflict.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — every state-transition action and the clock-set call — return `200 OK`. The administrative clock endpoint is the only path outside the `/gc` mount.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to a UTC instant | CourtClerk |
| POST | `/gc/protected-persons` | Register a protected person | Petitioner, CourtClerk |
| GET | `/gc/protected-persons/{id}` | Read a protected person | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/protected-persons` | List protected persons | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/fiduciaries` | Register a candidate fiduciary | CourtClerk, Petitioner |
| GET | `/gc/fiduciaries/{id}` | Read a fiduciary | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/fiduciaries` | List fiduciaries | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/cases` | Open a guardianship/conservatorship case | Petitioner, CourtClerk |
| GET | `/gc/cases/{id}` | Read a case | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/cases` | List cases (filter by `protected_person_id`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/cases/{id}/open-review` | Open court review on an active case | Judge |
| POST | `/gc/cases/{id}/close-review` | Close court review, return case to active | Judge |
| POST | `/gc/cases/{id}/terminate` | Terminate the case; cascade revoke/close | Judge |
| POST | `/gc/cases/{id}/restore` | Restore capacity and end the case | Judge |
| POST | `/gc/petitions` | File the petition that opens proceedings | Petitioner |
| GET | `/gc/petitions/{id}` | Read a petition | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/petitions` | List petitions (filter by `case_id` or `nominated_fiduciary_id`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/petitions/{id}/find-probable-cause` | Find probable cause to proceed | Judge |
| POST | `/gc/petitions/{id}/order-evaluation` | Order a capacity evaluation | Judge |
| POST | `/gc/petitions/{id}/grant` | Grant the petition | Judge |
| POST | `/gc/petitions/{id}/dismiss` | Dismiss the petition | Judge |
| POST | `/gc/evaluations` | Draft a capacity evaluation on a petition | CourtExaminer |
| GET | `/gc/evaluations/{id}` | Read an evaluation | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/evaluations` | List evaluations (filter by `petition_id`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/evaluations/{id}/file` | File (lock) the evaluation | CourtExaminer |
| POST | `/gc/appointments` | Create the appointment | Judge |
| GET | `/gc/appointments/{id}` | Read an appointment | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/appointments` | List appointments (filter by `case_id` or `fiduciary_id`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/appointments/{id}/qualify` | Qualify the fiduciary; issue letters; activate the case | Judge |
| POST | `/gc/appointments/{id}/suspend` | Suspend the fiduciary; freeze the account | Judge |
| POST | `/gc/appointments/{id}/reinstate` | Reinstate a suspended fiduciary; unfreeze the account | Judge |
| POST | `/gc/appointments/{id}/remove` | Remove the fiduciary; optionally disqualify for cause | Judge |
| GET | `/gc/bonds/{id}` | Read a bond | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/bonds` | List bonds (filter by `appointment_id`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/bonds/{id}/post` | Post the bond with a penal sum and surety | Fiduciary |
| POST | `/gc/bonds/{id}/approve` | Approve the posted bond | Judge |
| POST | `/gc/bonds/{id}/reject` | Reject the posted bond; return to required | Judge |
| POST | `/gc/restricted-accounts` | Open a court-restricted account | Fiduciary, CourtClerk |
| GET | `/gc/restricted-accounts/{id}` | Read a restricted account | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/restricted-accounts` | List restricted accounts (filter by `case_id`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/inventories` | Create the sworn inventory of the estate | Fiduciary |
| GET | `/gc/inventories/{id}` | Read an inventory | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/inventories` | List inventories (filter by `case_id`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/inventories/{id}/file` | File the inventory with the court | Fiduciary |
| POST | `/gc/inventories/{id}/approve` | Approve the inventory; fund the account | Judge |
| POST | `/gc/budgets` | Draft an annual budget with per-category caps | Fiduciary |
| GET | `/gc/budgets/{id}` | Read a budget | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/budgets` | List budgets (filter by `case_id` or `period_year`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/budgets/{id}/submit` | Submit the budget for approval | Fiduciary |
| POST | `/gc/budgets/{id}/approve` | Approve the budget (OCC-guarded); supersede prior | Judge |
| POST | `/gc/expenditures` | Request a disbursement; auto-route by threshold (OCC-guarded) | Fiduciary |
| GET | `/gc/expenditures/{id}` | Read an expenditure | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/expenditures` | List expenditures (filter by `case_id`, `budget_id`, or `status`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/expenditures/{id}/approve` | Approve a court-required expenditure | Judge |
| POST | `/gc/expenditures/{id}/deny` | Deny an expenditure; release any hold | Judge |
| POST | `/gc/expenditures/{id}/disburse` | Disburse an approved expenditure; debit account and budget | Fiduciary |
| POST | `/gc/accountings` | Draft an annual accounting report | Fiduciary |
| GET | `/gc/accountings/{id}` | Read an accounting report | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/accountings` | List accounting reports (filter by `case_id` or `period_year`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/accountings/{id}/submit` | Submit the accounting; recompute derived figures | Fiduciary |
| POST | `/gc/accountings/{id}/return` | Return the accounting for correction | Judge |
| POST | `/gc/accountings/{id}/resubmit` | Resubmit a corrected accounting | Fiduciary |
| POST | `/gc/accountings/{id}/approve` | Approve the accounting; advance due date, credit income | Judge |
| POST | `/gc/care-plans` | Draft a visitation/care plan | Fiduciary |
| GET | `/gc/care-plans/{id}` | Read a care plan | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/care-plans` | List care plans (filter by `case_id`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/care-plans/{id}/activate` | Activate a care plan; reject window overlap | Fiduciary |
| POST | `/gc/care-plans/{id}/replace` | Mark an active care plan replaced | Fiduciary |
| POST | `/gc/reviews` | Schedule a court review over a polymorphic subject | Judge, CourtClerk |
| GET | `/gc/reviews/{id}` | Read a court review | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| GET | `/gc/reviews` | List court reviews (filter by `case_id`) | Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk |
| POST | `/gc/reviews/{id}/hold` | Hold the scheduled review | Judge |
| POST | `/gc/reviews/{id}/dispose` | Dispose the held review with an outcome | Judge |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PERSON_HAS_ACTIVE_CASE` | 409 |
| `ERR_EVALUATION_NOT_ORDERED` | 409 |
| `ERR_EVALUATION_FINDS_COMPETENT` | 409 |
| `ERR_SCOPE_EXCEEDS_RECOMMENDATION` | 409 |
| `ERR_FIDUCIARY_DISQUALIFIED` | 409 |
| `ERR_BOND_INSUFFICIENT` | 409 |
| `ERR_BOND_NOT_APPROVED` | 409 |
| `ERR_NO_RESTRICTED_ACCOUNT` | 409 |
| `ERR_CASE_NOT_ACTIVE` | 409 |
| `ERR_CASE_NOT_UNDER_REVIEW` | 409 |
| `ERR_BUDGET_CAP_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_RESTRICTED_FUNDS` | 409 |
| `ERR_ACCOUNT_FROZEN` | 409 |
| `ERR_ACCOUNTING_VARIANCE` | 409 |
| `ERR_ACCOUNTING_OUTSTANDING` | 409 |
| `ERR_PENDING_EXPENDITURES` | 409 |
| `ERR_CARE_PLAN_OVERLAP` | 409 |
| `ERR_REVIEW_WINDOW_NOT_OPEN` | 409 |
| `ERR_OPEN_REVIEW_PENDING` | 409 |
| `ERR_RESTORATION_NOT_REVIEWED` | 409 |
