# Municipal Court Diversion API — Product Requirements Document

## 1. Introduction

This document specifies the backend service that runs a municipal court's pretrial diversion program end to end. The court processes minor citations — infractions and low-level misdemeanors — and offers eligible first-time offenders an alternative to conviction: a diversion agreement that swaps a formal sentence for community-service hours, education classes, and a schedule of fines and fees. A case that is completed in good standing is dismissed and referred for expungement; a case whose defendant falls out of compliance is defaulted, generates a bench warrant, and can later be reinstated during an amnesty window.

The system is, at its heart, a compliance-and-audit ledger wrapped around a workflow engine. A single **Case** is the central record that everything else hangs from: the charges filed against it, the arraignment hearing where a plea is entered, the diversion agreement that governs the defendant's obligations, the financial ledger that tracks what is owed and paid, and — when things go wrong — the warrant that issues and the reinstatement that recalls it. Because money, service hours, and case status all move together as operations cascade across these records, the service must keep derived totals reconciled at every step and must serialize competing writes so that no operator acts on a stale view of an account.

The remainder of this document defines the global contracts every endpoint obeys (Section 2), the domain workflows and the business rules scattered through them (Section 3), the full endpoint catalogue (Section 4), and the error code catalogue (Section 5). Section 2 is a precise contract and must be read literally; Section 3 is where the behavioral rules live and must be assembled across subsections to implement a given operation correctly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, a caller identifier, and `X-User-Role`, one of the recognized role names. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If both headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Authentication is always checked before authorization.

The system recognizes exactly six roles, spelled precisely as follows:

- **`CourtClerk`** — dockets citations into cases, adds charges, schedules arraignments, and submits expungement referrals.
- **`Judge`** — enters or accepts pleas, grants diversion, waives service assignments, dismisses cases, issues warrants, and reinstates failed cases.
- **`ProbationOfficer`** — creates service assignments, logs progress against them, and verifies their completion.
- **`Cashier`** — creates installment plans, records payments, and reverses payments.
- **`Defendant`** — acts on their own case: enters a plea, accepts a diversion offer, and makes payments.
- **`CourtAdmin`** — manages the reference data (courtrooms, service sites, amnesty programs) and the server's logical clock.

Five of the six roles carry an **opaque** identity: when `X-User-Role` is `CourtClerk`, `Judge`, `ProbationOfficer`, `Cashier`, or `CourtAdmin`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier where a workflow calls for it — for example, the `ProbationOfficer` who creates a service assignment has their `X-User-ID` stored on that assignment as `assigned_by_officer_id` — but it never compares an opaque identifier to any entity's `id`.

The `Defendant` role is **entity-backed**: when `X-User-Role` is `Defendant`, `X-User-ID` is the `id` of the acting `Defendant` record. Ownership checks on any resource that references a `Defendant` compare the resource's owning `defendant_id` (reached through the case) to `X-User-ID`; a mismatch is rejected with `ERR_UNAUTHORIZED` (HTTP 403). In particular, a defendant entering a plea must be the defendant on that case (their `X-User-ID` must equal the case's `defendant_id`), and a defendant making a payment may only pay against their own case's account.

All GET reads are available to every role — `CourtClerk`, `Judge`, `ProbationOfficer`, `Cashier`, `Defendant`, and `CourtAdmin` — with no per-defendant ownership restriction on reads: any role, including a `Defendant`, may GET any resource regardless of who owns it. The defendant ownership check constrains only the defendant-actable write operations (entering a plea, accepting a diversion, recording a payment). Write operations are restricted to the roles named in the endpoint catalogue of Section 4. Two write operations are shared: entering a plea is available to both `Defendant` and `Judge`, and recording a payment is available to both `Cashier` and `Defendant`.

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

### 2.3. Pagination

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0. Results are always returned sorted by `created_at` in ascending order (oldest first), so pagination is stable as new resources are added.

List responses set `response_type` to `"array"` and populate the pagination block inside `meta`: `limit` and `offset` echo the effective values used, `total_count` reports the total number of matching records across all pages, and `has_more` is true when records remain beyond the current page. Filtered list endpoints apply their filters before pagination, so `total_count` reflects the filtered set.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits, set once at creation and never changed. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that starts at 1 and increments by 1 on each mutation of that resource. A direct mutation of a resource refreshes its `updated_at` and bumps its `version`, with two documented carve-outs: recomputing a resource's derived fields alone (Section 2.10) touches neither, and several `LedgerAccount` mutations refresh `updated_at` without bumping `version` (Section 2.8).

Each resource that moves through a lifecycle additionally carries a `status` field holding its current state as one of the exact uppercase strings enumerated for that entity in Section 3; a client never writes `status` directly, since it is advanced only by the transitions described there.

There is one deliberate exception: the **`Payment`** resource is an immutable ledger entry and carries only `id` and `created_at`. It has no `updated_at` and no `version`. Reversing a payment does not mutate the payment's own version (there is none); instead it flips the payment's `reversed` flag and records the reversal's effect on the account, as described in Section 3.

### 2.5. The Logical Clock

All time-based rules in this system are evaluated against a server-controlled **logical clock**, never the real wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly advanced it continues to read that default. A `CourtAdmin` may move the clock forward (or to any instant) by supplying a target instant as `to_iso8601`; deadlines, amnesty windows, and due dates are all judged against whatever the clock currently reads. Every reference in this document to "now" means the current reading of this logical clock.

### 2.6. Nested Resource Retrieval and Path Validation

Many endpoints address a resource through a nested path — for example, the charges of a case, or the payments of a ledger account. Path parameters are validated left to right: each named resource in the path must exist before the next segment is considered, and the first missing one determines the error. Each resource type has its own not-found error: a missing case yields `ERR_CASE_NOT_FOUND`, a missing defendant `ERR_DEFENDANT_NOT_FOUND`, a missing charge `ERR_CHARGE_NOT_FOUND`, a missing courtroom `ERR_COURTROOM_NOT_FOUND`, a missing arraignment `ERR_ARRAIGNMENT_NOT_FOUND`, a missing diversion agreement `ERR_DIVERSION_NOT_FOUND`, a missing service site `ERR_SERVICE_SITE_NOT_FOUND`, a missing service assignment `ERR_SERVICE_ASSIGNMENT_NOT_FOUND`, a missing ledger account `ERR_LEDGER_ACCOUNT_NOT_FOUND`, a missing payment `ERR_PAYMENT_NOT_FOUND`, a missing amnesty program `ERR_AMNESTY_PROGRAM_NOT_FOUND`, and a missing expungement referral `ERR_EXPUNGEMENT_REFERRAL_NOT_FOUND`. All not-found errors carry HTTP 404.

### 2.7. Monetary Precision and Rounding

All monetary amounts — fines, fees, surcharges, assessed totals, payments, and installment amounts — are expressed in US dollars and carried to two decimal places. Unless a rule states otherwise, every computed money value is rounded half up to two decimal places. Where a rule composes several operations (for example, a surcharge that is rounded and then capped), the rounding is applied at the point the rule specifies, and the order matters; those points are called out explicitly in Section 3. Installment amounts are computed in whole cents using floor division, with the leftover remainder absorbed by the final installment, as detailed with the payment plan workflow.

### 2.8. Optimistic Concurrency on Ledger Accounts

Creating an installment plan is guarded by optimistic concurrency against the target ledger account. A create-installment-plan request must carry `expected_ledger_account_version`, a mandatory field holding the `version` of the `LedgerAccount` the client last observed. Before the plan is created, the server compares this value to the account's current `version`; if they do not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no plan is created. Because applying a payment and creating a superseding plan each bump the account's `version`, a client that read the account before such a change and then attempts to build a plan on that outdated view is turned away — it must re-read the account and retry with the fresh `version`. No other endpoint takes a version field; only the create-installment-plan operation participates in this concurrency check. The account's `version` is incremented only when a payment is recorded, a payment is reversed, or an installment plan is created; the other account mutations — finalizing the assessment when diversion is granted, settling to `SETTLED`, adding the late penalty when a warrant issues, the reinstatement adjustment, and closing at dismissal — refresh the account's `updated_at` but leave its `version` unchanged.

### 2.9. Validation Order and Failure Precedence

When a request could fail more than one check, the checks are evaluated in a fixed precedence so that the returned error is deterministic. The order is:

1. **Authentication** — headers present, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may perform the operation, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every resource named in the path exists, validated left to right, else the resource-specific 404 not-found error.
4. **State** — the target resource is in a state that permits the requested transition. A disallowed transition yields `ERR_INVALID_STATE` (409). At this same tier, a payment or plan against a closed account yields `ERR_ACCOUNT_CLOSED` (409), a plea on an arraignment whose plea is already recorded yields `ERR_INVALID_PLEA` (422), and a reverse against an already-reversed payment yields `ERR_PAYMENT_ALREADY_REVERSED` (409).
5. **Concurrency** — the optimistic-concurrency version check on installment-plan creation, else `ERR_STALE_VERSION` (412).
6. **Business referential** — first-offender eligibility (`ERR_NOT_FIRST_OFFENDER`, 422) and charge/assignment eligibility (`ERR_CHARGE_NOT_ELIGIBLE`, 422).
7. **Business temporal** — deadline and window checks: `ERR_ARRAIGNMENT_DEADLINE_PASSED` (422), `ERR_AMNESTY_WINDOW_CLOSED` (422), and `ERR_DEADLINE_NOT_PASSED` (422).
8. **Business safety** — segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, 403) and the completion gates `ERR_DIVERSION_NOT_COMPLETE` (409), `ERR_LEDGER_NOT_SETTLED` (409), and `ERR_ASSIGNMENT_NOT_VERIFIABLE` (409).
9. **Business constraint** — courtroom double-booking (`ERR_COURTROOM_DOUBLE_BOOKED`, 409), service-site capacity (`ERR_SERVICE_SITE_AT_CAPACITY`, 409), installment-count range (`ERR_INVALID_INSTALLMENT_COUNT`, 422), and installment minimum balance (`ERR_INSTALLMENT_MINIMUM_NOT_MET`, 422).
10. **Fiscal** — overpayment (`ERR_OVERPAYMENT`, 422).
11. **Body validation** — required fields present, correct types, valid enum values, else `ERR_VALIDATION` (400).

Where several checks share a tier, the specific error each raises is fixed by the failing condition; the tiers exist so that, for example, an authorization failure is never masked by a state failure that would also apply. The reason a lower-numbered tier is checked first is that it represents a more fundamental precondition (you cannot evaluate state on a resource that does not exist, and you cannot evaluate business rules on a request the caller was not allowed to make).

### 2.10. Conserved Quantities and Derived-Field Reconciliation

Several fields are **derived** — they are never written directly by a client but are recomputed from their inputs whenever those inputs change, and they must always reconcile. On a diversion agreement, `assigned_service_hours` is the sum of `required_hours` over the agreement's service assignments whose status is not `WAIVED`; `completed_service_hours` is the sum of `completed_hours` over assignments that are `COMPLETED`; and `completed_class_sessions` is the count of `EDUCATION_CLASS` assignments that are `COMPLETED`. On a ledger account, `collected_amount` is the sum of `amount` over the account's payments whose `reversed` flag is false, and `balance` is `assessed_amount` minus `collected_amount`. Whenever an assignment is progressed, verified, or waived, whenever a payment is recorded or reversed, and whenever an assessment is recomputed, the affected derived fields are recomputed immediately so that the stored totals never drift from their source rows. The compliance percentages (`provisional_compliance_pct` and `final_compliance_pct`) are likewise recomputed on every event that can move them, as detailed in Section 3. Recomputing a resource's derived fields does not by itself bump that resource's `version` or refresh its `updated_at`; those advance only on a direct transition or field write to the resource — so, for example, creating or progressing a service assignment, or recording a payment, updates the owning diversion agreement's derived totals in place without changing the agreement's own `version` or `updated_at`.

## 3. Business Logic & Workflows

### 3.1. Reference Data and the Court Environment

Before any case can move, a `CourtAdmin` stands up the fixed environment the court operates within. Courtrooms are created with a display `name`, a short `room_code`, and a `changeover_buffer_minutes` value; the buffer is optional on creation and defaults to 15 minutes when omitted. The buffer represents the changeover time the room needs both before and after each hearing and must be zero or greater. Service sites are created with a `name`, a `site_type` that is either `COMMUNITY_SERVICE` or `EDUCATION_CLASS`, and a `concurrent_capacity` — the maximum number of assignments whose sessions may overlap in time at that site, which must be at least 1. Amnesty programs are created with a `name`, a `penalty_waiver_pct` between 0 and 1 inclusive (the fraction of accrued late penalty that reinstatement under the program forgives), a `reinstatement_fee` of zero or more, and an activation window bounded by `active_from` (inclusive) and `active_to` (exclusive).

The `CourtAdmin` also owns the logical clock described in Section 2.5. Advancing the clock is a test-driving capability: the admin supplies a target instant as `to_iso8601`, and the server's notion of "now" moves to that instant. This capability returns no resource body. All temporal rules downstream — arraignment deadlines, program deadlines, amnesty windows, and installment due dates — read from this clock.

### 3.2. Registering Defendants and Docketing Citations

A `CourtClerk` registers each defendant with a `full_name`, a `date_of_birth` given as an ISO date, and a contact `email`. The clerk may also seed a known `prior_diversion_count`; when omitted it defaults to 0, and it may never be negative. This count is the linchpin of first-offender eligibility: the system treats a defendant as a first offender only while their `prior_diversion_count` is below the first-offender ceiling, which the court sets at 1. In practice that means a defendant with no prior completed diversion (a count of 0) qualifies, and a defendant with one or more priors does not. The count is not static — each time a case is dismissed, the owning defendant's `prior_diversion_count` is incremented by one, so a defendant who completes one diversion is no longer a first offender for any future case.

The clerk dockets a citation by creating a case, supplying the `defendant_id` of the cited person, the issuing agency's `citation_number`, and the `offense_date` on which the cited offense occurred. A new case opens in `DOCKETED` status. At docket time the system computes the case's `arraignment_deadline`: it takes the `offense_date` at midnight UTC (`00:00:00Z`) and adds the arraignment window of 30 days. A plea must be entered at or before that instant; the deadline is stored on the case and drives a temporal check later.

Charges are added to a case one at a time by a `CourtClerk`. Each charge carries the owning `case_id`, an `offense_code` naming the municipal ordinance, a `severity` of either `INFRACTION` or `MISDEMEANOR`, a `base_fine_amount` of zero or more USD before any multiplier or fee, and an `is_diversion_eligible` flag that defaults to true when omitted. Charges are immutable once created; the full set of a case's charges — regardless of any status — is the input to the fine assessment. A case's charges can be listed back in creation order, and a defendant's cases can be listed through the reverse of the case's `defendant_id` relationship.

### 3.3. Scheduling the Arraignment Hearing

A `CourtClerk` schedules an arraignment against a case, naming the `courtroom_id` where the hearing will sit and the half-open interval it occupies via `scheduled_start` and `scheduled_end`. The end must be strictly later than the start. A newly scheduled hearing opens in `SCHEDULED` status.

Courtrooms cannot be double-booked, and the conflict test is buffer-aware. Each hearing reserves not just its own interval but that interval expanded by the room's `changeover_buffer_minutes` on both sides — the buffer minutes are subtracted from the start and added to the end. Two hearings in the same courtroom conflict when their buffer-expanded intervals overlap. If a requested booking's buffer-expanded interval overlaps that of any existing hearing in the same room, the request is rejected with `ERR_COURTROOM_DOUBLE_BOOKED`. Hearings in different rooms never conflict with one another. Arraignments can be listed and optionally filtered by `case_id` or by `courtroom_id`, reflecting the two foreign keys a hearing carries.

### 3.4. Entering the Plea and the Provisional Assessment

The arraignment is where the case first moves. Entering a plea records the defendant's `plea` — one of `GUILTY`, `NOT_GUILTY`, or `NO_CONTEST` — and holds the hearing. This action may be performed by the `Defendant` on their own case (their `X-User-ID` must equal the case's `defendant_id`) or by a `Judge` on the defendant's behalf. Entering the plea drives the arraignment from `SCHEDULED` to `HELD` and, in the same operation, advances the owning case from `DOCKETED` to `ARRAIGNED`.

Several conditions guard the plea. The arraignment must be in `SCHEDULED` status and its plea must not already be recorded; a second attempt on a hearing whose plea is already set, or a `plea` value outside the three allowed strings, is rejected with `ERR_INVALID_PLEA`. The plea must be entered while now is at or before the case's `arraignment_deadline`; a plea attempted after that instant is rejected with `ERR_ARRAIGNMENT_DEADLINE_PASSED`.

Holding the plea also opens the case's financial record. The system creates the case's `LedgerAccount` in `PROVISIONAL` status and computes its `assessed_amount` using the provisional variant of the fine assessment. The provisional assessment works as follows. First, a subtotal is formed by summing, over every charge on the case, that charge's `base_fine_amount` with no severity multiplier applied. A single surcharge rate is then chosen from that same subtotal: if the subtotal is at most 100 dollars the rate is 0.20; otherwise if the subtotal is at most 500 dollars the rate is 0.30; otherwise the rate is 0.35. The surcharge is the rate multiplied by the subtotal, rounded half up to two decimal places, and then capped so it never exceeds 150 dollars — the rounding happens first and the cap is applied to the rounded figure. The provisional `assessed_amount` is the subtotal plus a flat court fee of 50 dollars plus the surcharge. The program fee is not part of the provisional assessment. Because the account is only provisional at this stage, no severity multiplier and no program fee have yet entered the total.

### 3.5. Granting Diversion and Finalizing the Assessment

Once a case is `ARRAIGNED`, a `Judge` may grant pretrial diversion. Granting requires that the recorded plea be either `GUILTY` or `NO_CONTEST` — a `NOT_GUILTY` plea (or the absence of a recorded eligible plea) does not lead to diversion and is rejected with `ERR_INVALID_STATE` — and that the defendant still qualify as a first offender and that the case bear at least one eligible charge. If the defendant's `prior_diversion_count` is not below the first-offender ceiling of 1, the grant is rejected with `ERR_NOT_FIRST_OFFENDER`. If no charge on the case has `is_diversion_eligible` set to true, the grant is rejected with `ERR_CHARGE_NOT_ELIGIBLE`. When the grant proceeds, the case advances from `ARRAIGNED` to `DIVERSION_GRANTED`.

The judge sets the terms of the agreement at grant time: `mandated_service_hours` of community service (zero or more), a count of `required_class_sessions` (zero or more), a `program_fee` for administering the diversion (zero or more USD), and a `program_deadline` — the instant by which every requirement must be satisfied. The new diversion agreement opens in `OFFERED` status.

Granting diversion also finalizes the money. The ledger account transitions from `PROVISIONAL` to `ASSESSED`, and its `assessed_amount` is recomputed using the final variant of the fine assessment. The final variant differs from the provisional one in two ways. First, each charge's contribution to the subtotal is its `base_fine_amount` multiplied by the severity multiplier — 1.0 for an `INFRACTION` and 1.5 for a `MISDEMEANOR`. The surcharge tiering, the half-up rounding of the surcharge, and the 150-dollar cap are applied to this new subtotal exactly as before, and the flat court fee of 50 dollars is added. Second, the agreement's `program_fee` is added to the final total. The result is the final `assessed_amount`, and because it now reflects severity and the program fee it is generally higher than the provisional figure the defendant saw at plea.

After a grant, the `Defendant` accepts the diversion terms; acceptance requires the owning case to be in `DIVERSION_GRANTED` and moves the agreement from `OFFERED` to `IN_PROGRESS`, with no other effect beyond the status change and the refreshed `updated_at`. Only once the agreement is `IN_PROGRESS` can service work be assigned and progressed against it.

### 3.6. Service Assignments: Assigning, Progressing, Verifying, and Waiving

A `ProbationOfficer` assigns community-service or class work against an `IN_PROGRESS` diversion agreement. Each assignment names the owning `diversion_id`, the `service_site_id` that will host it, an `assignment_type` of `COMMUNITY_SERVICE` or `EDUCATION_CLASS`, the `required_hours` the assignment covers (zero or more; for a class this is session-equivalent hours), and the half-open session window given by `session_start` and `session_end`, where the end must be strictly after the start. The `assignment_type` must match the hosting site's `site_type`; a mismatch is rejected with `ERR_CHARGE_NOT_ELIGIBLE`. A new assignment opens in `ASSIGNED` status.

Two things happen when an assignment is created. The officer's `X-User-ID` is stored on the assignment as `assigned_by_officer_id`; this is the record that later enforces segregation of duties. And the agreement's `assigned_service_hours` is recomputed as the sum of `required_hours` over all of the agreement's assignments that are not `WAIVED`. Site capacity is enforced at assignment time: the number of the site's assignments whose session windows overlap in time may not exceed the site's `concurrent_capacity`. Every assignment at the site counts toward this limit regardless of its status — a `WAIVED` or `COMPLETED` assignment still occupies its slot — and windows that merely abut (one's `session_end` equal to another's `session_start`) do not overlap. If adding this assignment would push the count of time-overlapping sessions at the site above that capacity, it is rejected with `ERR_SERVICE_SITE_AT_CAPACITY`. Assignments can be listed and filtered by `diversion_id` or by `service_site_id`.

Progress is logged by a `ProbationOfficer` supplying `hours_logged`, which must be greater than zero. Logging progress adds `hours_logged` to the assignment's `completed_hours` and, the first time it happens, moves the assignment from `ASSIGNED` to `IN_PROGRESS`. Each progress event recomputes the owning agreement's `provisional_compliance_pct`.

Verifying completion is where the segregation constraint bites. A `ProbationOfficer` verifies an assignment, moving it from `IN_PROGRESS` to `COMPLETED`, but only under three guards evaluated in the safety tier. The verifier's `X-User-ID` must differ from the assignment's `assigned_by_officer_id` — the officer who created an assignment may not be the one who verifies it — and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. The assignment's `completed_hours` must be at least its `required_hours`; a shortfall is rejected with `ERR_ASSIGNMENT_NOT_VERIFIABLE`. And the owning agreement must itself be `IN_PROGRESS` for the verify to be a legal transition; otherwise it is rejected with `ERR_INVALID_STATE`. Verification recomputes the agreement's `completed_service_hours`, `completed_class_sessions`, and `final_compliance_pct`.

A `Judge` may waive an assignment as a compensating action when it can no longer or need no longer be performed. Waiving is permitted from either `ASSIGNED` or `IN_PROGRESS` while the owning agreement is `IN_PROGRESS`, and in both cases the assignment moves to `WAIVED` and the agreement's `assigned_service_hours` is recomputed so that the waived assignment's `required_hours` drops out of the conserved total. A `WAIVED` assignment is treated as satisfied for the purpose of the completion gate but contributes nothing to the completed-hours or completed-sessions totals.

**Compliance percentages.** Both compliance figures blend three weighted components: a service component weighted 0.5, a class component weighted 0.3, and a financial component weighted 0.2. The service component is the assignment's logged-hours numerator divided by `mandated_service_hours`, capped at 1.0, and taken as 1.0 outright when `mandated_service_hours` is zero. The class component is the class-session numerator divided by `required_class_sessions`, capped at 1.0, and taken as 1.0 when `required_class_sessions` is zero. The financial component is the account's `collected_amount` divided by its `assessed_amount`, capped at 1.0, and taken as 1.0 when `assessed_amount` is zero. The percentage is 100 multiplied by the weighted sum of the three capped components, rounded half up to two decimal places. The two figures differ only in which assignments feed the numerators: for `provisional_compliance_pct`, the service numerator sums `completed_hours` over assignments whose status is `IN_PROGRESS` or `COMPLETED`, and the class numerator counts `EDUCATION_CLASS` assignments whose status is `IN_PROGRESS` or `COMPLETED`; for `final_compliance_pct`, both numerators count only assignments that are `COMPLETED` (verified). The provisional figure is refreshed on progress logging; the final figure is refreshed on verification and reaches 100 when the agreement is fully satisfied.

**The completion cascade.** When an assignment is verified, the system checks whether the agreement can now complete. The agreement transitions from `IN_PROGRESS` to `COMPLETED` only when every one of its assignments is in `COMPLETED` or `WAIVED` status, its `completed_service_hours` is at least its `mandated_service_hours`, its `completed_class_sessions` is at least its `required_class_sessions`, and — a cross-entity gate — the case's ledger account is already in `SETTLED` status. If all service and completion conditions are met but the ledger account is not `SETTLED`, the completion is blocked with `ERR_LEDGER_NOT_SETTLED`; in that case the verify request that triggered the check is itself rejected with that error and the assignment is left `IN_PROGRESS` rather than advancing to `COMPLETED` (its tentative completion is rolled back). When the agreement does reach `COMPLETED`, `final_compliance_pct` is recomputed to 100, the case bubbles up from `DIVERSION_GRANTED` to `COMPLIED`, and an expungement referral is created for the case in `PENDING` status with its `eligible_date` set to now.

### 3.7. The Ledger: Payments, Installment Plans, and Reversals

The case's `LedgerAccount` is a one-to-one record — a case has exactly one, retrievable both directly and as the reverse of the account's `case_id` (returned as an array of zero or one). The account tracks three money figures introduced in Section 2.10: `assessed_amount` (what is owed), `collected_amount` (the sum of non-reversed payment amounts), and `balance` (assessed minus collected). It moves through `PROVISIONAL`, `ASSESSED`, `SETTLED`, and `CLOSED`.

**Recording a payment.** A payment is recorded against an account by a `Cashier`, or by the `Defendant` against their own case's account. The payment carries the target `ledger_account_id` and an `amount`, which must be strictly greater than zero. The amount is distributed across the account's outstanding buckets by a fixed-order waterfall: the buckets are filled in the order fines first, then court fee, then state surcharge, then program fee. Starting from the full payment amount as the remaining pool, each bucket in turn absorbs the smaller of the remaining pool and that bucket's outstanding amount; the absorbed figure is recorded on the payment as `allocated_fines`, `allocated_court_fee`, `allocated_surcharge`, and `allocated_program_fee` respectively, and the remaining pool is reduced by that figure before moving to the next bucket. Overpayment is judged against the account's current `balance` (`assessed_amount` minus `collected_amount`): if the payment `amount` exceeds that `balance`, the payment is rejected with `ERR_OVERPAYMENT` and nothing is applied. Because the late penalty is not one of the four waterfall buckets, when a penalty is present a payment may exhaust all four buckets yet still carry a residual that is within the allowed `balance`; that residual is collected against the account (raising `collected_amount` and lowering `balance`) without appearing in any `allocated_*` field, so such a payment's `amount` can exceed the sum of its four allocation fields. A payment opens with its `reversed` flag false.

Recording a payment refreshes `collected_amount` (the sum of amounts over the account's non-reversed payments) and recomputes `balance`. If the balance reaches exactly zero, the account bubbles from `ASSESSED` to `SETTLED`, and any `ACTIVE` installment plan on the account moves to `PAID_OFF`. Reaching `SETTLED` is the financial precondition that lets a fully-served diversion agreement complete, as described in Section 3.6.

**Installment plans.** A `Cashier` may set up an installment plan against an account, subject to the optimistic-concurrency guard of Section 2.8: the request carries `num_installments` and `expected_ledger_account_version`. The number of installments must be between 2 and 12 inclusive; a value outside that range is rejected with `ERR_INVALID_INSTALLMENT_COUNT`. The account's `balance` must be at least 100 dollars to qualify for a plan; a balance below that minimum is rejected with `ERR_INSTALLMENT_MINIMUM_NOT_MET`. The plan cannot be created against a `CLOSED` account (`ERR_ACCOUNT_CLOSED`), and the supplied `expected_ledger_account_version` must match the account's current `version` or the request is rejected with `ERR_STALE_VERSION`.

The schedule is computed in whole cents to avoid rounding drift. The account's `balance` at creation is converted to a total number of cents (rounded to the nearest cent). That total is divided by the number of installments using floor division to give the per-installment cents; the `installment_amount` carried by each of the first installments is that floored figure expressed in dollars. The remainder — the total cents minus the floored per-installment cents multiplied by the number of installments — is added onto the floored figure to form the `final_installment_amount`, so the last installment absorbs the entire rounding remainder rather than spreading it. The plan's `next_due_date` is set to 30 days after now. A new plan opens in `ACTIVE` status. Creating a plan increments the account's `version` by one; if a prior plan on the same account was `ACTIVE`, that prior plan is moved to `SUPERSEDED` and the newly created plan takes its place as the active schedule. Plans can be listed as the reverse of the plan's `ledger_account_id`.

**Reversing a payment.** A `Cashier` may reverse a payment as a compensating action. Reversal sets the payment's `reversed` flag to true, which drops its `amount` out of `collected_amount`, and the account's `balance` is recomputed. A payment that has already been reversed cannot be reversed again; a second attempt is rejected with `ERR_PAYMENT_ALREADY_REVERSED`. If reversing a payment that had settled the account restores a positive balance, the account moves back from `SETTLED` to `ASSESSED` — a compensation edge that re-opens a previously settled account. Payments can be listed as the reverse of the payment's `ledger_account_id`.

### 3.8. Failure to Comply, Warrants, and Reinstatement

When a diverted defendant misses the program deadline, a `Judge` declares failure to comply and issues a warrant. This is permitted only while the case is in `DIVERSION_GRANTED` and only after the program window has closed: now must be strictly past the agreement's `program_deadline`. A warrant requested while now is still at or before that deadline is rejected with `ERR_DEADLINE_NOT_PASSED`. Issuing the warrant advances the case from `DIVERSION_GRANTED` to `FAILED_TO_COMPLY` and sets off a chain of cascading effects. The diversion agreement moves to `DEFAULTED` — from `IN_PROGRESS`, or from `OFFERED` if the defendant had not yet accepted the offer. Caused by that default, a `Warrant` is created in `ISSUED` status with a human-readable `reason` recorded on it (the server generates this `reason` string itself; it is not supplied in the request body), and any `ACTIVE` installment plan on the case's ledger account is demoted from `ACTIVE` to `DELINQUENT`. In the same operation a late penalty of 75 dollars is added to the account's `assessed_amount`, and the `balance` is recomputed to reflect it. A case's warrants can be listed as the reverse of the warrant's `case_id`.

A failed case can be brought back during an amnesty window. A `Judge` reinstates a case in `FAILED_TO_COMPLY`, supplying the `amnesty_program_id` of the program under which relief is sought. Reinstatement is allowed only while the referenced program's window is open — now must be at or after its `active_from` and strictly before its `active_to`; a reinstatement attempted outside that half-open window is rejected with `ERR_AMNESTY_WINDOW_CLOSED`. When reinstatement proceeds, the case cycles back from `FAILED_TO_COMPLY` to `DIVERSION_GRANTED`, the diversion agreement returns from `DEFAULTED` to `IN_PROGRESS`, the outstanding `Warrant` moves from `ISSUED` to `RECALLED`, and any `DELINQUENT` installment plan on the account returns to `ACTIVE`.

Reinstatement also adjusts the money. The late penalty of 75 dollars that was added when the warrant issued is partly forgiven: the waived portion is 75 dollars multiplied by the program's `penalty_waiver_pct`, rounded half up to two decimal places. The account's `assessed_amount` is reduced by that waived amount and then increased by the program's `reinstatement_fee`, and the `balance` is recomputed from the new assessed amount and the existing `collected_amount`. This adjustment runs once per reinstatement against the account's current assessed figure.

### 3.9. Compliance, Dismissal, and Expungement Referral

A case reaches `COMPLIED` automatically, not by a direct call: it bubbles up from `DIVERSION_GRANTED` the moment its diversion agreement reaches `COMPLETED`, which — per Section 3.6 — itself required the ledger account to already be `SETTLED`. At that bubble-up the case's expungement referral is created in `PENDING` status with its `eligible_date` stamped at now.

A `Judge` then dismisses a complied case. Dismissal is permitted only while the case is in `COMPLIED` and only when the diversion agreement is `COMPLETED`; an attempt to dismiss while the agreement is not yet `COMPLETED` is rejected with `ERR_DIVERSION_NOT_COMPLETE`. Dismissing advances the case from `COMPLIED` to `DISMISSED`, increments the owning defendant's `prior_diversion_count` by one (which is what removes their first-offender status for future cases), and moves the ledger account from `SETTLED` to `CLOSED`. A closed account is frozen: any later payment or plan against it is rejected with `ERR_ACCOUNT_CLOSED`.

Finally, a `CourtClerk` submits the expungement referral once the case is disposed. Submission is permitted only while the owning case is in `DISMISSED`; an attempt before dismissal is rejected with `ERR_INVALID_STATE`. Submitting moves the referral from `PENDING` to `SUBMITTED`. A case's expungement referrals can be listed as the reverse of the referral's `case_id`.

## 4. Endpoint Definitions

Endpoints that create a brand-new resource return HTTP 201; endpoints that modify or transition an existing resource, and the clock-setting capability, return HTTP 200. All read endpoints return HTTP 200. Request and response bodies are not restated here — reconstruct them from the workflows in Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a supplied instant | CourtAdmin |
| POST | `/courtrooms` | Create a courtroom | CourtAdmin |
| GET | `/courtrooms/{id}` | Fetch a courtroom | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/service-sites` | Create a community-service / education-class site | CourtAdmin |
| GET | `/service-sites/{id}` | Fetch a service site | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/amnesty-programs` | Create an amnesty program window | CourtAdmin |
| POST | `/defendants` | Register a defendant | CourtClerk |
| GET | `/defendants/{id}` | Fetch a defendant | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| GET | `/defendants/{id}/cases` | List a defendant's cases | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/cases` | Docket a citation into a new case | CourtClerk |
| GET | `/cases/{id}` | Fetch a case | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/cases/{id}/charges` | Add a charge to a case | CourtClerk |
| GET | `/cases/{id}/charges` | List a case's charges | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/cases/{id}/arraignments` | Schedule an arraignment in a courtroom | CourtClerk |
| GET | `/arraignments/{id}` | Fetch an arraignment | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| GET | `/arraignments` | List arraignments, optionally filtered by case or courtroom | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/arraignments/{id}/plea` | Enter the plea and hold the arraignment | Defendant, Judge |
| POST | `/cases/{id}/diversion-agreements` | Grant pretrial diversion and finalize the assessment | Judge |
| GET | `/cases/{id}/diversion-agreements` | List a case's diversion agreements | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/diversion-agreements/{id}/accept` | Accept the diversion terms | Defendant |
| POST | `/diversion-agreements/{id}/service-assignments` | Assign community-service / class work | ProbationOfficer |
| GET | `/service-assignments/{id}` | Fetch a service assignment | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| GET | `/service-assignments` | List service assignments, optionally filtered by diversion or site | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/service-assignments/{id}/progress` | Log hours toward an assignment | ProbationOfficer |
| POST | `/service-assignments/{id}/verify-completion` | Verify an assignment complete (segregation-of-duties enforced) | ProbationOfficer |
| POST | `/service-assignments/{id}/waive` | Waive an assignment | Judge |
| GET | `/cases/{id}/ledger-account` | Fetch the case's ledger account | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| GET | `/ledger-accounts/{id}` | Fetch a ledger account | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/ledger-accounts/{id}/installment-plans` | Create an installment plan (OCC on account version) | Cashier |
| GET | `/ledger-accounts/{id}/installment-plans` | List an account's installment plans | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/ledger-accounts/{id}/payments` | Record a payment | Cashier, Defendant |
| GET | `/ledger-accounts/{id}/payments` | List an account's payments | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/payments/{id}/reverse` | Reverse a payment | Cashier |
| POST | `/cases/{id}/dismiss` | Dismiss a complied case | Judge |
| POST | `/cases/{id}/warrant` | Declare failure-to-comply and issue a warrant | Judge |
| GET | `/cases/{id}/warrants` | List a case's warrants | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/cases/{id}/reinstate` | Reinstate a failed case under an amnesty window | Judge |
| GET | `/cases/{id}/expungement-referrals` | List a case's expungement referrals | CourtClerk, Judge, ProbationOfficer, Cashier, Defendant, CourtAdmin |
| POST | `/expungement-referrals/{id}/submit` | Submit an expungement referral | CourtClerk |

## 5. Error Code Catalogue

The trigger condition for each error is described in the Section 2 and Section 3 narratives that govern the relevant operation; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_DEFENDANT_NOT_FOUND | 404 |
| ERR_CASE_NOT_FOUND | 404 |
| ERR_CHARGE_NOT_FOUND | 404 |
| ERR_COURTROOM_NOT_FOUND | 404 |
| ERR_ARRAIGNMENT_NOT_FOUND | 404 |
| ERR_DIVERSION_NOT_FOUND | 404 |
| ERR_SERVICE_SITE_NOT_FOUND | 404 |
| ERR_SERVICE_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_LEDGER_ACCOUNT_NOT_FOUND | 404 |
| ERR_PAYMENT_NOT_FOUND | 404 |
| ERR_AMNESTY_PROGRAM_NOT_FOUND | 404 |
| ERR_EXPUNGEMENT_REFERRAL_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ACCOUNT_CLOSED | 409 |
| ERR_INVALID_PLEA | 422 |
| ERR_PAYMENT_ALREADY_REVERSED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_NOT_FIRST_OFFENDER | 422 |
| ERR_CHARGE_NOT_ELIGIBLE | 422 |
| ERR_ARRAIGNMENT_DEADLINE_PASSED | 422 |
| ERR_AMNESTY_WINDOW_CLOSED | 422 |
| ERR_DEADLINE_NOT_PASSED | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_DIVERSION_NOT_COMPLETE | 409 |
| ERR_LEDGER_NOT_SETTLED | 409 |
| ERR_ASSIGNMENT_NOT_VERIFIABLE | 409 |
| ERR_COURTROOM_DOUBLE_BOOKED | 409 |
| ERR_SERVICE_SITE_AT_CAPACITY | 409 |
| ERR_INVALID_INSTALLMENT_COUNT | 422 |
| ERR_INSTALLMENT_MINIMUM_NOT_MET | 422 |
| ERR_OVERPAYMENT | 422 |
