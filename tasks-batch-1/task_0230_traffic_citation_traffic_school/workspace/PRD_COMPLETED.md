# Traffic Citation Payment & Traffic School API — Product Requirements Document

## 1. Introduction

This document specifies the Traffic Citation Payment & Traffic School API, a back-office system that carries a traffic citation from the moment an officer issues it through to its final disposition — paid in full, dismissed at a hearing, or voided by the court. The platform serves four distinct constituencies that rarely act in concert: a **Driver** who looks up, pays, contests, or enrolls against their own citations; a court clerk who runs the day-to-day docket; a hearing officer who adjudicates disputes; and a DMV administrator who owns the driver's license standing and demerit-point ledger. Each citation is simultaneously a financial instrument and a legal matter, and the API is built around the observation that those two dimensions advance on independent tracks: a citation can be halfway paid while a contest is still pending before a judge.

The system's central challenge is reconciliation. Money flows in through one-off payments and structured installment plans; fees accrue through court charges, statutory surcharges, late penalties, collections referrals, and traffic-school administration; and every one of these movements must be reflected immediately in a single authoritative balance that the driver pays down. Layered on top of the ledger is a web of compliance consequences — license holds, failure-to-appear warrants, and automatic point suspensions — each of which is opened and released by cascades that ripple outward from a single state change. The requirements below treat correctness of those cascades, and the precise arithmetic behind every fee, as the product's defining quality.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_AUTH` (HTTP 401). When the headers are well-formed but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes exactly four roles: `Driver`, `CourtClerk`, `HearingOfficer`, and `DmvAdmin`.

The `Driver` role is entity-backed. When `X-User-Role` is `Driver`, the value of `X-User-ID` is the `id` of the acting `Driver` record; ownership checks on any resource that references a driver compare that resource's driver foreign key to `X-User-ID`. Concretely, when a `Driver` posts a payment, requests an installment plan, files a contest, enrolls in traffic school, or cancels a plan, the citation (or the citation behind the plan or enrollment) must belong to that driver — its `driver_id` must equal `X-User-ID` — or the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The other three roles are operator identities. When `X-User-Role` is `CourtClerk`, `HearingOfficer`, or `DmvAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it, but it is never compared to any entity's `id` for ownership. A `CourtClerk` runs court operations (creating citations and charges, assessment, voiding, late penalties, hearing scheduling, failure-to-appear, plan default, collections referral, school completion and failure, warrant quashing, and the test clock). A `HearingOfficer` adjudicates contests — granting continuances and deciding the verdict. A `DmvAdmin` owns license-hold releases and the point ledger, and shares jurisdiction and driver creation and the test clock with the clerk.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. Out-of-range `limit` values are silently clamped rather than rejected: a `limit` below 1 is raised to 1 and a `limit` above 100 is lowered to 100. The `offset` parameter is the count of items to skip from the front of the result and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint says otherwise, list results are ordered by each resource's `created_at` timestamp in ascending order.

Every list response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every persisted resource is minted with a server-generated `id` formatted as a UUID, carrying no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 and increases by exactly one on each mutation of the resource.

There is one deliberate exception. A `PointLedgerEntry` is an append-and-mask audit record rather than a mutable resource; it carries only `id` and `created_at`. It has no `updated_at` and no `version`. When the system masks a point entry as part of a traffic-school reduction, that is modeled as a state change on the entry's `state` field, but the entry itself does not expose the standard mutation bookkeeping that other resources do.

The `version` integer is the anchor for optimistic concurrency (see §2.6). Whenever the requirements speak of "bumping the version" of a citation, they mean this monotonic counter advancing by one, accompanied by a refreshed `updated_at`.

### 2.5. Monetary Precision and Rounding

All money in this system is held and exchanged in integer **cents**; there are no fractional-cent amounts anywhere in a stored field or a response body. Most arithmetic — summing charges, adding the flat court fee, subtracting payments — is exact integer addition and subtraction and needs no rounding.

Two computations introduce a percentage and therefore a rounding step: the statutory surcharge at assessment and the collections fee at referral. In both cases the percentage product is rounded to the nearest whole cent using the **round-half-up** convention (a result whose fractional part is exactly one half rounds upward). Wherever this document refers to rounding a money term, it means round-half-up to a whole number of cents.

### 2.6. Optimistic Concurrency on Installment-Plan Creation

Creating an installment plan against a citation is a versioned write guarded by optimistic concurrency control. The create request must carry `expected_citation_version`, the `version` of the target citation the client last observed. Before the plan is built, the server compares `expected_citation_version` against the citation's current `version`. If they do not match — because some other writer (a payment, a penalty, a fee, or a prior plan supersede) has advanced the citation's `version` since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no plan is created. This guards the re-financing semantics of plan creation: because a new plan supersedes any prior active plan, a create that still carries the pre-advance version is operating on a stale view of the citation's balance, penalty, or prior plan, and must be refused rather than allowed to overwrite state it never saw. No other endpoint accepts or requires a version field; plan creation is the only versioned write.

### 2.7. Hierarchical Consistency and Cascading Reconciliation

The defining characteristic of this domain is that a single operation frequently mutates several entities at once, and the system must apply every such cascade atomically and immediately. When a citation reaches its paid state, the chain of consequences runs three levels deep: any open nonpayment or failure-to-appear hold tied to that citation is released, releasing the hold re-derives the driver's license standing, and that re-derivation in turn re-evaluates whether the driver's demerit points still warrant a point suspension. The same composite philosophy governs dismissal, voiding, late penalties, plan defaults, failure-to-appear, traffic-school completion, and point posting. The detailed cascades live in §3 alongside the workflows that trigger them; the principle here is that no client ever has to issue a follow-up call to keep derived fields consistent — the server reconciles license standing, point balances, warrant flags, and citation balances in the same transaction as the triggering write.

Three driver fields are always derived, never written directly. The `license_status` is `VALID` when the driver has no open holds, `HELD` when at least one hold is open but none of them is a point suspension, and `SUSPENDED` whenever any open hold is a point suspension — a point suspension always dominates a concurrent nonpayment or failure-to-appear hold. The `point_balance` is the running sum of the driver's active demerit-point entries inside a rolling window. The `fta_warrant_active` flag is true exactly when the driver has at least one active warrant. Each of these is recomputed on demand and as a side effect of any operation that could change its inputs.

### 2.8. Nested Lookups and Left-to-Right Existence

The topology is flat: each collection sits at the API root, and entities are joined by foreign-key fields rather than by URL nesting. A handful of write endpoints still address a parent in the path (for example, posting a payment, plan, contest, or enrollment under a citation). For any such path, the server validates each identifier in left-to-right order and rejects the first one that does not resolve with `ERR_NOT_FOUND` (HTTP 404) before evaluating any business rule. Read endpoints accept optional filter parameters that perform reverse lookups from a foreign key — for instance, listing the charges of a citation, the installments of a plan, or the holds of a driver.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a missing or malformed credential yields `ERR_MISSING_AUTH` before anything else is considered. Role authorization is next, yielding `ERR_FORBIDDEN_FOR_ROLE`. The system then confirms that every resource named in the path exists, left to right, yielding `ERR_NOT_FOUND`. For driver-initiated actions, resource ownership is checked next, yielding `ERR_NOT_RESOURCE_OWNER`. Only then are state-machine preconditions evaluated, with an out-of-state target yielding `ERR_INVALID_STATE`; followed by time-gating checks yielding `ERR_NOT_YET_LATE`; followed by the remaining business constraints described throughout §3. Request-body well-formedness — required fields present, enum values legal, numeric fields non-negative where required, and `citation_number` and `license_number` unique within their jurisdiction — is enforced with `ERR_INVALID_REQUEST` (HTTP 400); logically this body check sits immediately after authentication and before resource existence, even though it is the lowest-numbered constraint in the rule table.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Jurisdiction and Its Fee Schedule

Every citation inherits its economics from a **Jurisdiction**, which a clerk or DMV administrator creates with the court's full fee schedule. The payload carries a `name`, a two-letter `state_code`, and the monetary and policy parameters that drive every downstream calculation: a flat `base_court_fee_cents` added to each citation at assessment; a `surcharge_pct` expressed as a fraction of the base fine (for example, 0.20 means twenty percent); a flat `late_penalty_cents` charged once when a citation passes its deadline unresolved; an `installment_setup_fee_cents` folded into a plan's principal at activation; a `min_installment_cents` floor below which a computed installment base is rejected; a `collections_fee_pct` applied to the outstanding balance at referral; and a `traffic_school_fee_cents` administrative charge added when a school enrollment opens.

Several policy thresholds carry defaults when the creator omits them. The `collections_age_days` (default 30) is the number of days past the deadline at which an unresolved citation becomes referable to collections. The `school_eligible_max_points` (default 1) is the maximum total demerit points a citation's charges may carry and still qualify for traffic school. The `school_cooldown_months` (default 18) caps how often a driver may complete traffic school. The `point_suspension_threshold` (default 4) is the demerit-point total at or above which a driver is automatically suspended, and the `point_window_months` (default 12) is the rolling window over which active point entries are summed. A jurisdiction is readable by any role.

### 3.2. Registering Drivers and the Citation's Two Tracks

A clerk or DMV administrator registers a **Driver** by supplying the `jurisdiction_id` they belong to, a `license_number` that must be unique within that jurisdiction, and a `full_name`. The `jurisdiction_id` arrives in the request body; a value that does not resolve to a jurisdiction is rejected with `ERR_INVALID_REQUEST` (HTTP 400), not `ERR_NOT_FOUND`. A freshly registered driver begins with a `license_status` of `VALID`, a `point_balance` of zero, and `fta_warrant_active` false; all three are derived rather than stored, as described in §2.7. Drivers can be listed and filtered by `jurisdiction_id` or `license_number`.

A `CourtClerk` opens a **Citation** in `DRAFT` against a driver by supplying the `driver_id`, a `citation_number` unique within the jurisdiction, the `issued_at` instant the officer wrote it (which also serves as the point-effective date should points ever post), and the `appear_by` deadline that governs late penalties, collections, and failure-to-appear. The `driver_id` arrives in the request body rather than the URL path; a `driver_id` that does not resolve to a driver is rejected with `ERR_INVALID_REQUEST` (HTTP 400), not `ERR_NOT_FOUND`. A new citation starts with `financial_status` of `DRAFT`, `adjudication_status` of `NONE`, `disposition` of `OPEN`, and `version` 1. The two status fields are independent: `financial_status` tracks money (`DRAFT`, `ASSESSED`, `PARTIALLY_PAID`, `PAID`, `VOID`) and `adjudication_status` tracks the legal dispute (`NONE`, `CONTESTED`, `DISMISSED`, `UPHELD`). The `disposition` flips from `OPEN` to `CLOSED` exactly when the citation becomes `PAID`, when its adjudication becomes `DISMISSED`, or when it becomes `VOID`. Citations are readable by any role and can be listed and filtered by `driver_id`, `citation_number`, or `financial_status`.

### 3.3. Charges and Statutory Assessment

While a citation is still a `DRAFT`, a clerk attaches one or more **CitationCharge** line items, each a vehicle-code `violation_code`, a human-readable `description`, a statutory `base_fine_cents`, and the `points` (0, 1, or 2) the violation carries on the DMV ledger. The charge carries its target citation as a `citation_id` in the request body rather than the URL path; a `citation_id` that does not resolve to a citation is rejected with `ERR_INVALID_REQUEST` (HTTP 400), not `ERR_NOT_FOUND`. Charges may be attached only while the citation is in `DRAFT`; an attempt to add a charge to a citation in any other `financial_status` is rejected with `ERR_INVALID_STATE`. Each new charge recomputes the citation's `base_fine_cents` as the sum of its charges' base fines; this recompute refreshes the citation's `updated_at` but does not advance its `version` (so the citation remains at `version` 1 throughout `DRAFT` until assessment performs the first version bump). Charges are immutable once created and can be listed by `citation_id`.

Assessment is the act of freezing the statutory total and is performed by a clerk advancing the citation from `DRAFT` to `ASSESSED`. The citation must already carry at least one charge — an attempt to assess a citation with no charges is rejected with `ERR_NO_CHARGES` — and it must currently be in `DRAFT`, else the transition is rejected with `ERR_INVALID_STATE`. These two preconditions are evaluated state-first per the §2.9 ordering: the `DRAFT` state check runs before the charge-presence check, so a citation that is not in `DRAFT` is rejected with `ERR_INVALID_STATE` even when it also carries no charges, while a `DRAFT` citation with no charges is rejected with `ERR_NO_CHARGES`. On assessment the server sums the charges into `base_fine_cents`, then freezes `assessed_total_cents` as follows: the surcharge is the base fine multiplied by the jurisdiction's surcharge fraction, rounded half-up to a whole cent; the assessed total is then the base fine plus the flat court fee plus that rounded surcharge. The surcharge is computed on the base fine **only** and never on the court fee, and the evaluation order is pinned — the surcharge is rounded *before* the integer court fee is added, so the court fee never sits inside the rounding boundary. The citation's `balance_cents` is set equal to `assessed_total_cents`, `financial_status` becomes `ASSESSED`, and the citation's `version` increases by one.

### 3.4. The Authoritative Balance and Paying It Down

Once a citation is assessed it carries a live, authoritative `balance_cents`. That balance is always the frozen `assessed_total_cents` plus accumulated `penalty_cents` minus `amount_paid_cents`, where `amount_paid_cents` is the chronological running sum of every `POSTED` payment for the citation, ordered by `posted_at` ascending; reversed payments are excluded from the sum. The `penalty_cents` accumulator holds every after-assessment fee — late penalty, collections fee, and traffic-school fee — added on top of the frozen statutory total.

A `Driver` (or a clerk acting on their behalf) pays by posting a **Payment** under the citation with an `amount_cents` greater than zero, a `method` of `CARD`, `CASH`, or `CHECK`, and optionally an `installment_id` when the tender is meant to satisfy a specific installment rather than the free-form citation balance. When supplied, the `installment_id` arrives in the request body and must resolve to an existing installment, else the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400); a posted payment that targets an installment still in `SCHEDULED` flips that installment to `PAID`. The tendered `amount_cents` must be positive and must not exceed the current `balance_cents`; a non-positive amount or an amount above the balance is rejected with `ERR_OVERPAYMENT`. The citation must also be `OPEN` and in a payable `financial_status` of `ASSESSED` or `PARTIALLY_PAID`, else the payment is rejected with `ERR_INVALID_STATE`; the `OPEN` disposition is checked first, so a citation that is `OPEN` but still in `DRAFT` is rejected with `ERR_INVALID_STATE` for not being payable. The state checks precede the overpayment check, so an out-of-state citation yields `ERR_INVALID_STATE` even when the tendered amount is itself invalid. A posted payment is recorded with `status` `POSTED` and a server-stamped `posted_at`, after which `amount_paid_cents` and `balance_cents` are recomputed and the citation's `version` advances by one. A payment may later be reversed, moving its `status` to `REVERSED` and removing it from the paid total. Payments are readable and can be listed by `citation_id` or `installment_id`.

When a payment leaves the balance still above zero, an `ASSESSED` citation moves to `PARTIALLY_PAID`, and a citation already `PARTIALLY_PAID` stays there. When a payment drives the balance exactly to zero — the amount must equal the outstanding balance, since anything larger is an overpayment — the citation becomes `PAID` and its `disposition` flips to `CLOSED`. Reaching `PAID` sets off the deepest cascade in the system: any open nonpayment or failure-to-appear hold for this citation is released; releasing each hold re-derives the driver's `license_status`; that re-derivation re-evaluates the driver's point suspension; any active warrant for the citation is quashed and the driver's `fta_warrant_active` flag is re-derived; and any active installment plan is marked `COMPLETED` with its remaining scheduled installments flipped to `PAID`. The citation's `version` advances by one.

### 3.5. Installment Plans and Their Forward-Looking Schedule

When a driver cannot pay at once, they (or a clerk) request an **InstallmentPlan** under the citation. The request carries the `term_count` of monthly installments desired and the `first_due_at` date of the first installment, and — because plan creation is the system's only versioned write — an `expected_citation_version` (see §2.6). The `term_count` must fall between 2 and 12 inclusive. At activation the server snapshots the citation's current `balance_cents` and adds the jurisdiction's setup fee to form the plan's `principal_cents`, which is frozen for the life of the plan. The nominal per-installment base is the principal divided by the term count, taking the floor (the integer quotient), and is stored as `installment_cents`. The whole-number remainder left over — the principal minus the base times the term count — is not spread across the schedule; instead the final installment absorbs the entire remainder. Concretely, each of the first term-count-minus-one installments is scheduled for the base amount, and the last installment is scheduled for the base plus the remainder. If the computed base falls below the jurisdiction's `min_installment_cents`, or the requested `term_count` is outside the 2-to-12 range, the plan is rejected with `ERR_INSTALLMENT_TOO_SMALL`.

The plan materializes its schedule as a set of **Installment** rows, each carrying its parent `installment_plan_id`, a one-based `sequence_no`, a `due_at` date that is the first due date advanced by one month for each step past the first, the scheduled `amount_cents` for that step, and a `status` that begins `SCHEDULED` and becomes `PAID` as payments land or `MISSED` when the plan is abandoned. Installments are readable and can be listed by `installment_plan_id`; plans themselves can be listed by `citation_id` or `status`.

The plan schedule and the citation balance are deliberately two different views of the same debt. The schedule is forward-looking and never mutates: the sum of the scheduled installment amounts equals `principal_cents` exactly by construction, because the base covers every term and the remainder is folded into the last. The citation's `balance_cents`, by contrast, is the chronological applied view — it reflects only payments that have actually posted and diverges from the schedule the moment an installment is missed or only partially paid. The schedule stands still; the citation balance is what moves.

Because a new plan re-finances the citation, creating one supersedes any prior active plan: that prior plan moves from `ACTIVE` to `SUPERSEDED` and its still-`SCHEDULED` installments flip to `MISSED`, and the citation's `version` advances by one. Plan creation advances the citation's `version` by exactly one whether or not it supersedes a prior plan — the supersede and the new-plan write together constitute a single versioned mutation, not two. A plan completes when all of its installments are `PAID` or when the citation itself reaches `PAID`, at which point it moves from `ACTIVE` to `COMPLETED`. A driver or clerk may cancel an `ACTIVE` plan, moving it to `CANCELLED` and flipping its scheduled installments to `MISSED`, but only when no posted payment has been allocated to any of the plan's installments; a cancel attempted with such a payment present is rejected with `ERR_HAS_PAYMENTS`.

### 3.6. Default, Late Penalty, and the License Holds They Open

A citation that drifts past its deadline accrues consequences, all of them clock-gated against a server clock that the court can advance for testing. Applying the flat **late penalty** is a clerk action available on a citation whose `financial_status` is `ASSESSED` or `PARTIALLY_PAID`. The server clock must have reached or passed the `appear_by` deadline — an attempt before that instant is rejected with `ERR_NOT_YET_LATE` — and the penalty must not already have been applied, guarded by the `late_penalty_applied` flag; a second attempt is rejected with `ERR_PENALTY_ALREADY_APPLIED`. Applying it once adds the jurisdiction's `late_penalty_cents` to `penalty_cents`, sets `late_penalty_applied` true, recomputes the balance, and — as a cascade — opens a nonpayment **LicenseHold** for the citation if none is already open, re-deriving the driver's `license_status` to `HELD`. The citation's `version` advances by one. An attempt to apply the penalty when the citation is in neither `ASSESSED` nor `PARTIALLY_PAID` is rejected with `ERR_INVALID_STATE`.

A clerk may mark an `ACTIVE` installment plan as **defaulted** once at least one of its installments is past its `due_at` while still `SCHEDULED`; an attempt against a plan in any status other than `ACTIVE` is rejected with `ERR_INVALID_STATE`, and on an `ACTIVE` plan where no installment is yet past due the action is rejected with `ERR_NOT_YET_LATE`. The past-due comparison is strict: an installment qualifies only once the server clock is strictly after its `due_at`, so a clock exactly at `due_at` does not yet make the plan defaultable. Default moves the plan from `ACTIVE` to `DEFAULTED`, flips every past-due installment to `MISSED`, and cascades a nonpayment hold open for the citation if none is already open, re-deriving the driver's `license_status` to `HELD`.

A **LicenseHold** records its `driver_id`, the `citation_id` that caused it (absent for a point suspension), a `hold_type` of `FTA_HOLD`, `NONPAYMENT_HOLD`, or `POINT_SUSPENSION`, a `status` of `OPEN` or `RELEASED`, and a `released_at` timestamp set on release. Holds are opened only by cascades — late penalty, plan default, failure-to-appear, and point suspension — and are cleared either by a cascade (payment, dismissal, school completion) or by an explicit DMV release. When a `DmvAdmin` releases a hold, the hold must currently be `OPEN` — a release targeting a hold that is already `RELEASED` is rejected with `ERR_INVALID_STATE` — and the release condition must be met: for a nonpayment or failure-to-appear hold, the linked citation must already be `CLOSED`; for a point suspension, the driver's `point_balance` must have fallen below the jurisdiction's `point_suspension_threshold`. A release attempted while its condition is unmet is rejected with `ERR_HOLD_CONDITION_UNMET`. The point-suspension release threshold is the same inclusive boundary as the open side: the balance must be strictly below the threshold, so a balance still at or above the threshold yields `ERR_HOLD_CONDITION_UNMET`. A successful release sets `status` to `RELEASED`, stamps `released_at`, and re-derives the driver's `license_status`. Holds are readable and can be listed by `driver_id`, `citation_id`, or `status`.

### 3.7. Contesting a Citation: Hearings, Continuances, and Verdicts

A `Driver` may dispute a citation by filing a **ContestRequest** under it, supplying the `grounds` for the contest. Filing one opens the request in `REQUESTED` and sets the citation's `adjudication_status` to `CONTESTED`. A citation that is already `CONTESTED`, `DISMISSED`, or `UPHELD` cannot accept a second contest; the attempt is rejected with `ERR_ALREADY_CONTESTED`. The request tracks a `hearing_at` time (set once a hearing is scheduled), a `continuance_count` that begins at zero, and a `status` that walks `REQUESTED`, `HEARING_SET`, `CONTINUANCE`, and the terminal `DISMISSED`, `UPHELD`, or `FTA`. Contests are readable and can be listed by `citation_id`.

A `CourtClerk` schedules the hearing, moving the request from `REQUESTED` to `HEARING_SET` and recording the supplied `hearing_at`, which must be in the future relative to the server clock; a hearing time at or before the current server clock is rejected with `ERR_INVALID_HEARING_DATE`. Scheduling is permitted only from `REQUESTED` or `CONTINUANCE`; an attempt from any other state is rejected with `ERR_INVALID_STATE`, which is evaluated before the `hearing_at` future-date check. The track is cyclic: a `HearingOfficer` may grant a continuance, moving the request from `HEARING_SET` to `CONTINUANCE`, incrementing `continuance_count` by one and clearing the `hearing_at`; a continuance attempted from any state other than `HEARING_SET` is rejected with `ERR_INVALID_STATE`. From `CONTINUANCE` the clerk schedules again back to `HEARING_SET` with a new future `hearing_at`. At most two continuances may be granted — a third request, when `continuance_count` has already reached 2, is rejected with `ERR_CONTINUANCE_LIMIT`; this limit check is evaluated after the `HEARING_SET` state check.

From `HEARING_SET`, a `HearingOfficer` decides the matter by supplying a `verdict` that must be exactly `DISMISS` or `UPHOLD` — a missing or otherwise-valued `verdict` is rejected with `ERR_INVALID_REQUEST` — and the two verdicts are mirror images of each other. A `verdict` of `DISMISS` moves the request to `DISMISSED`, sets the citation's `adjudication_status` to `DISMISSED`, and closes the citation's `disposition`; as a cascade the citation's `balance_cents` is forced directly to zero because the charges are vacated, with `financial_status` left untouched unless it was already `PAID`, any open hold for the citation released, any active warrant quashed, and no points posted. A `verdict` of `UPHOLD` moves the request to `UPHELD` and sets the citation's `adjudication_status` to `UPHELD`; as a cascade the server posts one **PointLedgerEntry** with `state` `ACTIVE` for each charge whose `points` are greater than zero, and those new entries re-evaluate the driver's point suspension, potentially opening a point-suspension hold and re-deriving the driver's `license_status` to `SUSPENDED`. Deciding a request that is not in `HEARING_SET` is rejected with `ERR_INVALID_STATE`.

Should the driver not appear, the clerk records a **failure to appear** from `HEARING_SET` once the server clock has passed the scheduled `hearing_at` — an attempt at or before that instant is rejected with `ERR_NOT_YET_LATE` (the boundary is strict, so a clock exactly at `hearing_at` is not yet a failure to appear), and an attempt from any state other than `HEARING_SET` with `ERR_INVALID_STATE`, the state check being evaluated before the time-gating check. Failure to appear moves the request's `status` to `FTA` while leaving the citation's `adjudication_status` at `CONTESTED`, and cascades three levels deep: it creates an `ACTIVE` **Warrant** whose `reason` is `FTA_HEARING`, the warrant opens a failure-to-appear hold for the citation, and that hold re-derives the driver's `license_status` to `HELD`.

### 3.8. Warrants and the Demerit-Point Ledger

A **Warrant** carries its `citation_id`, its `driver_id`, a `reason` of `FTA_HEARING` or `FTA_APPEAR`, a `status` of `ACTIVE` or `QUASHED`, and a `quashed_at` timestamp set on quashing. A clerk may quash a warrant, moving it from `ACTIVE` to `QUASHED`, only when the warrant is currently `ACTIVE` — a quash targeting a warrant that is already `QUASHED` is rejected with `ERR_INVALID_STATE` — and only once its condition is met: the underlying citation's `disposition` is `CLOSED`, or the contest behind it has a fresh future `hearing_at` scheduled (a contest in `HEARING_SET` whose `hearing_at` is strictly after the server clock); otherwise the quash is rejected with `ERR_HOLD_CONDITION_UNMET`. Quashing stamps `quashed_at` and re-derives the driver's `fta_warrant_active`. Warrants are readable and can be listed by `citation_id`, `driver_id`, or `status`.

The **PointLedgerEntry** is the DMV's demerit-point record. Each entry carries its `driver_id`, the `citation_id` it stems from, the `points` posted, an `effective_at` date equal to the source citation's `issued_at` (which drives the rolling window), and a `state` of `ACTIVE` or `MASKED`. The driver's `point_balance` is the sum of the `points` over the driver's `ACTIVE` entries whose `effective_at` falls on or after the window start, where the window start is the current moment less the jurisdiction's `point_window_months`; masked entries are excluded from the sum. Whenever this balance is recomputed, the suspension boundary is inclusive: when the `point_balance` is greater than or equal to the jurisdiction's `point_suspension_threshold`, the system opens a point-suspension hold if none is open and the driver's `license_status` becomes `SUSPENDED`; a balance of exactly threshold-minus-one does not suspend. When the re-evaluation finds the balance has fallen below the threshold, any open point-suspension hold is released (its `status` set to `RELEASED` with `released_at` stamped), mirroring the open side; this release fires as part of the same re-evaluation triggered by point posting, the citation-paid cascade, or traffic-school masking, and is in addition to — not in place of — the explicit `DmvAdmin` release of §3.6. Point ledger entries are readable and can be listed by `driver_id`, `citation_id`, or `state`.

### 3.9. Traffic School and Point Reduction

Traffic school lets a qualifying driver erase demerit points by completing a course. A `Driver` (or clerk) enrolls under a citation by supplying the `completion_due_at` deadline; the enrollment also records the `driver_id` behind the citation, freezes `eligible_points` as the total `points` across the citation's charges at the moment of enrollment, opens with `status` `ENROLLED`, and starts `points_reduced` at zero. Opening an enrollment adds the jurisdiction's `traffic_school_fee_cents` to the citation's `penalty_cents`, recomputes the balance, and advances the citation's `version` by one. Enrollments are readable and can be listed by `citation_id` or `driver_id`.

Eligibility is checked at enrollment. The total demerit points across the citation's charges must not exceed the jurisdiction's `school_eligible_max_points`; the driver must not have completed traffic school within the jurisdiction's `school_cooldown_months`; the citation must not be `VOID`; and the citation's `adjudication_status` must be neither `CONTESTED` nor `DISMISSED`. A request that fails any of these is rejected with `ERR_SCHOOL_INELIGIBLE`.

A clerk marks the course **completed**, moving the enrollment from `ENROLLED` to `COMPLETED`. The enrollment must currently be `ENROLLED`, else the request is rejected with `ERR_INVALID_STATE`; this state check precedes the deadline and fine checks. Completion is allowed only when the server clock has not yet passed the `completion_due_at` — a late completion is rejected with `ERR_SCHOOL_DEADLINE_PASSED`, evaluated before the fine check — and only when the citation's `financial_status` is already `PAID`, since the fine must be settled first; an unpaid fine is rejected with `ERR_FINE_UNPAID`. The deadline comparison is strict: a clock exactly at `completion_due_at` is still on time, and only a clock strictly past it triggers `ERR_SCHOOL_DEADLINE_PASSED`. On completion the server freezes `points_reduced` as the smaller of the enrollment's `eligible_points` and the candidate total — the sum of `points` across the citation's still-`ACTIVE` point ledger entries — and masks that many points' worth of those entries by flipping their `state` from `ACTIVE` to `MASKED`. Entries are selected for masking in ascending `created_at` order, masking each whole entry whose `points` do not exceed the points still remaining to be reduced and skipping any entry that would overshoot; no entry is ever split, so the masked entries' `points` sum to exactly `points_reduced`. If the candidate total is zero (for instance, the citation was paid without ever being upheld, so no points were posted), `points_reduced` is zero and nothing is masked. Masking the entries re-evaluates the driver's point suspension and may release a point-suspension hold, re-deriving the driver's `license_status`.

A clerk marks an enrollment **failed** from `ENROLLED` once the server clock has passed the `completion_due_at`; an attempt at or before that instant is rejected with `ERR_NOT_YET_LATE` (the boundary is strict, so a clock exactly at `completion_due_at` is not yet failable), and an attempt against an enrollment not in `ENROLLED` is rejected with `ERR_INVALID_STATE`. Failure moves the enrollment to `FAILED` and masks no points.

### 3.10. Voiding, Collections, and Their Reconciliations

A `CourtClerk` may **void** a citation that is still `DRAFT` or `ASSESSED`, provided no posted payment exists against it — a void with payments present is rejected with `ERR_HAS_PAYMENTS`. For this void operation only, the posted-payment check is evaluated **before** the `DRAFT`/`ASSESSED` state precondition, overriding the general state-before-business-constraint precedence of §2.9: a citation that carries a posted payment is rejected with `ERR_HAS_PAYMENTS` (not `ERR_INVALID_STATE`) even though such a citation is no longer in `DRAFT` or `ASSESSED`. Voiding from `ASSESSED` additionally requires that the `adjudication_status` not be `UPHELD`, else it is rejected with `ERR_INVALID_STATE`. A void sets `financial_status` to `VOID`, closes the `disposition`, and — when voiding from `ASSESSED` — cascades to release any open hold for the citation and quash any active warrant. The citation's `version` advances by one.

When a citation ages unpaid past its deadline, a clerk refers it to **collections**. Referral is eligible only when the citation has aged at least the jurisdiction's `collections_age_days` past its `appear_by`, with the age measured as the whole number of days (the floor of the elapsed seconds divided by 86,400) between the deadline and now; the boundary is inclusive, so day N of the threshold qualifies while day N-minus-one does not. The citation must also still be `OPEN` with a `balance_cents` above zero. A referral attempted before the citation is eligible is rejected with `ERR_NOT_YET_LATE`. On referral the server records a **CollectionsReferral** whose `status` is `REFERRED`, freezes `outstanding_at_referral_cents` as the citation's current `balance_cents`, and computes `collections_fee_cents` as that outstanding amount multiplied by the jurisdiction's `collections_fee_pct`, rounded half-up to a whole cent. That fee is added once to the citation's `penalty_cents`, guarded by the `collections_referred` flag so it can never be applied twice; a referral attempted when the flag is already set is rejected with `ERR_PENALTY_ALREADY_APPLIED`, and this already-referred guard is checked before the age-eligibility check so a second attempt yields `ERR_PENALTY_ALREADY_APPLIED` rather than `ERR_NOT_YET_LATE`. After the fee is added the balance is recomputed and the citation's `version` advances by one. Collections referrals are readable and can be listed by `citation_id`. A referral is recalled — its `status` moving from `REFERRED` to `RECALLED` — automatically once the citation closes, whether by reaching `PAID`, by becoming `VOID`, or by an adjudication of `DISMISSED`.

### 3.11. The Test Clock

Because so many transitions are gated on real time — late penalty, failure to appear, plan default, school failure, and collections eligibility — the system exposes an administrative test-driving capability that advances the logical server clock to a supplied instant. A clerk or DMV administrator invokes it with a single `to_iso8601` value, and the server clock thereafter reports that instant for every subsequent time-gated comparison. This capability exists so the deadline-driven workflows can be exercised deterministically.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2 and the auth rules of §2.1. Resource-creating endpoints return HTTP 201 with the new resource; state transitions and other modifications return HTTP 200 with the updated resource; reads return HTTP 200. The request and response bodies are not restated here — reconstruct them from the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server clock for deterministic time-gated tests | CourtClerk, DmvAdmin |
| POST | `/jurisdictions` | Create a jurisdiction with its fee schedule and thresholds | CourtClerk, DmvAdmin |
| GET | `/jurisdictions/{jid}` | Get a jurisdiction | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/drivers` | Register a driver in a jurisdiction | CourtClerk, DmvAdmin |
| GET | `/drivers/{did}` | Get a driver (computed status, points, warrant flag) | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/drivers` | List/filter drivers | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/citations` | Create a draft citation | CourtClerk |
| GET | `/citations/{cid}` | Look up a citation | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/citations` | List/look up citations | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/citations/{cid}/assess` | Freeze the statutory total and move DRAFT → ASSESSED | CourtClerk |
| POST | `/citations/{cid}/void` | Void a citation (DRAFT or ASSESSED, no payments) | CourtClerk |
| POST | `/citations/{cid}/apply-late-penalty` | Apply the flat late penalty after appear_by | CourtClerk |
| POST | `/charges` | Add a charge to a draft citation | CourtClerk |
| GET | `/charges/{chid}` | Get a charge | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/charges` | List charges | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/citations/{cid}/payments` | Post a payment against the citation | Driver, CourtClerk |
| GET | `/payments/{pid}` | Get a payment | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/payments` | List payments | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/citations/{cid}/installment-plans` | Create an installment plan (supersedes prior active plan; OCC-guarded) | Driver, CourtClerk |
| GET | `/installment-plans/{pid}` | Get an installment plan | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/installment-plans` | List installment plans | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/installment-plans/{pid}/mark-default` | Mark a plan defaulted after a missed due date | CourtClerk |
| POST | `/installment-plans/{pid}/cancel` | Cancel an active plan (no payments allocated) | Driver, CourtClerk |
| GET | `/installments/{iid}` | Get an installment | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/installments` | List installments | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/citations/{cid}/contest-requests` | File a contest; set adjudication to CONTESTED | Driver |
| GET | `/contest-requests/{rid}` | Get a contest request | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/contest-requests` | List contest requests | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/contest-requests/{rid}/schedule` | Schedule (or re-schedule from CONTINUANCE) a hearing | CourtClerk |
| POST | `/contest-requests/{rid}/continue` | Grant a continuance (cyclic; max 2) | HearingOfficer |
| POST | `/contest-requests/{rid}/decide` | Rule DISMISS or UPHOLD | HearingOfficer |
| POST | `/contest-requests/{rid}/fail-to-appear` | Record failure to appear; create warrant and FTA hold | CourtClerk |
| POST | `/citations/{cid}/enrollments` | Enroll in traffic school; add school fee | Driver, CourtClerk |
| GET | `/enrollments/{eid}` | Get a traffic-school enrollment | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/enrollments` | List enrollments | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/enrollments/{eid}/complete` | Mark course completed; mask citation points | CourtClerk |
| POST | `/enrollments/{eid}/fail` | Mark course failed after the deadline | CourtClerk |
| POST | `/citations/{cid}/collections-referrals` | Refer an aged unpaid citation to collections; add fee | CourtClerk |
| GET | `/collections-referrals/{crid}` | Get a collections referral | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/collections-referrals` | List collections referrals | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/license-holds/{hid}` | Get a license hold | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/license-holds` | List license holds | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/license-holds/{hid}/release` | Release a hold once its condition is met | DmvAdmin |
| GET | `/warrants/{wid}` | Get a warrant | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/warrants` | List warrants | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| POST | `/warrants/{wid}/quash` | Quash a warrant once its condition is met | CourtClerk |
| GET | `/point-ledger/{pleid}` | Get a point ledger entry | CourtClerk, DmvAdmin, HearingOfficer, Driver |
| GET | `/point-ledger` | List point ledger entries | CourtClerk, DmvAdmin, HearingOfficer, Driver |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_AUTH | 401 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_NO_CHARGES | 409 |
| ERR_OVERPAYMENT | 409 |
| ERR_HAS_PAYMENTS | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_NOT_YET_LATE | 409 |
| ERR_PENALTY_ALREADY_APPLIED | 409 |
| ERR_INVALID_HEARING_DATE | 409 |
| ERR_CONTINUANCE_LIMIT | 409 |
| ERR_ALREADY_CONTESTED | 409 |
| ERR_SCHOOL_INELIGIBLE | 409 |
| ERR_FINE_UNPAID | 409 |
| ERR_SCHOOL_DEADLINE_PASSED | 409 |
| ERR_INSTALLMENT_TOO_SMALL | 409 |
| ERR_HOLD_CONDITION_UNMET | 409 |
| ERR_INVALID_REQUEST | 400 |
