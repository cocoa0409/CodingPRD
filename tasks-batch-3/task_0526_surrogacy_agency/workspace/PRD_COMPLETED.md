# Surrogacy & Egg-Donation Agency API — Product Requirements Document

## 1. Introduction

Building a family through gestational surrogacy is a multi-party undertaking that must reconcile the interests of intended parents, a gestational carrier, an optional egg donor, and the attorneys and clinicians who serve them. This API provides the operational backbone for a surrogacy and egg-donation agency, coordinating each arrangement from initial applicant intake and psychological screening, through matching negotiation and contract execution, into the medical journey with its clinical milestones, and finally to the legal parentage order that closes the case.

The system is deliberately conservative around money and consent. Funds committed by intended parents sit in an escrow account and are released only after the clinical milestones that justify each payment have actually been reached, and only when two different agency staff members — one who approves and a distinct one who releases — have each acted. Psychological clearance, insurance adequacy, cooling-off reflection windows, and jurisdiction-specific parentage rules all act as gates that a match or journey cannot skip. Because several parties read and write shared records over long periods, the API uses optimistic concurrency on the records most exposed to stale writes, so that a client cannot silently overwrite a decision it never observed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes five roles, spelled exactly as follows: `CaseManager`, `Screener`, `FinanceOfficer`, `IntendedParentActor`, and `CarrierActor`. A `CaseManager` runs applicant intake creation, matching negotiation, journey and milestone operations, and disbursement approval. A `Screener` performs intake screening, psychological clearance, insurance review, and match psychological clearance. A `FinanceOfficer` governs escrow deposits handling and disbursement release and is deliberately kept separate from disbursement approval. An `IntendedParentActor` is the intended parent acting on their own contract and escrow. A `CarrierActor` is the gestational carrier acting on their own contract.

The three agency-staff roles — `CaseManager`, `Screener`, and `FinanceOfficer` — are operator roles: when `X-User-Role` is any of these, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier where a transition writes it — for example, it stores the approving `CaseManager`'s `X-User-ID` as `approved_by_user_id` on a `Disbursement` — but it never compares that identifier to any entity's `id`. The two party roles are entity-backed. When `X-User-Role` is `IntendedParentActor`, `X-User-ID` is the `id` of the acting `IntendedParent`; ownership checks on any resource that references an `IntendedParent` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `CarrierActor`, `X-User-ID` is the `id` of the acting `GestationalCarrier`; ownership checks on any resource that references a `GestationalCarrier` compare the resource's foreign-key field to `X-User-ID`.

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

List endpoints are paginated through query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range from 1 to 100 inclusive, or a negative `offset`, is rejected with `ERR_VALIDATION_LIMIT`.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order, with any ties on identical `created_at` values broken by server-side creation order (the sequence in which the records were minted). Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Timestamps

Every entity in the system carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. All of the primary entities — intended parents, gestational carriers, egg donors, matches, contracts, escrow accounts, journeys, milestones, compensation-schedule lines, disbursements, and insurance reviews — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. The `version` starts at its initial value of `1` on creation and increments by one on every mutation of the resource, and `updated_at` is refreshed to the current time whenever the resource changes. Every entity in this system carries these full common fields; none is a create-only, immutable record. Updates to computed fields such as an escrow account's `available_cents` or a journey's `current_phase` are mutations in this sense — they refresh `updated_at` and increment `version` on the entity that owns them. Each lifecycle-bearing entity — matches, contracts, escrow accounts, journeys, milestones, disbursements, and insurance reviews, as well as intended parents, carriers, and donors through their `intake_status` — exposes its current lifecycle position through a `status` field whose permitted values are enumerated in the workflow that governs it.

### 2.5. Nested Resource Retrieval and Referential Existence

Several resources are addressed under a parent path — for example, a milestone, a compensation-schedule line, or a disbursement is reached through its owning journey. For any request whose path carries more than one identifier, the system validates each identifier from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource. A disbursement requested under a journey that does not exist fails on the journey before the disbursement is ever consulted. The same existence rule applies to foreign keys supplied in a request body: after the path identifiers resolve, referenced resources named in the body (such as a schedule line or an escrow account) must exist, and a missing one yields `ERR_NOT_FOUND`.

### 2.6. Monetary Precision

All monetary amounts in the system are integer cents, and every amount supplied on input must be zero or greater. This applies to an intended parent's `budget_cents`, a carrier's `base_compensation_cents`, a donor's `donor_compensation_cents`, a match's `proposed_carrier_comp_cents`, and a schedule line's `amount_cents`. Escrow counters are tracked exactly in integer cents. Where a calculation applies a percentage — the carrier experience bonus and the insurance gap premium — the intermediate figure is rounded half up to a whole number of cents at the pinned point described in the workflow that owns it, and all arithmetic remains exact in integer cents thereafter.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a record it has actually observed, using an optimistic-concurrency check keyed on the parent record's `version`.

The first is accepting a match. That request must carry `expected_match_version`, which must equal the target `Match`'s current `version`. If a counter or re-propose has advanced the match's `version` since the client last read it — changing the compensation being agreed to — the accept carries a stale value and is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot finalize a match on terms it never saw. The counter and re-propose operations likewise require `expected_match_version` to equal the match's current `version` and are rejected with `ERR_STALE_VERSION` (HTTP 412) on a mismatch.

The second is depositing into an escrow account. That request must carry `expected_escrow_version`, which must equal the target `EscrowAccount`'s current `version`. If a prior deposit or a cascaded freeze has advanced the account's `version` since the client last read it, the deposit carries a stale value and is rejected with `ERR_STALE_VERSION` (HTTP 412) before it can breach the budget cap on stale data. Endpoints that are not one of these do not take a version field.

### 2.8. Segregation of Duties

Disbursing escrow funds is a two-person control. The `CaseManager` who approves a disbursement is recorded, by their `X-User-ID`, in the disbursement's `approved_by_user_id`. The subsequent release must be performed by a `FinanceOfficer` whose `X-User-ID` differs from that recorded approver. A release where the acting officer's identifier equals the recorded approver is rejected with `ERR_SEGREGATION_OF_DUTIES`, preventing any single person from both authorizing and paying out the same funds.

### 2.9. Escrow Reconciliation Invariant

Each escrow account maintains three running counters in integer cents: `deposited_cents` (cumulative funds the intended parent has deposited), `disbursed_cents` (cumulative funds actually released to recipients), and `reserved_cents` (funds committed to approved-but-not-yet-released disbursements). Its computed balance, `available_cents`, always equals `deposited_cents` minus `disbursed_cents` minus `reserved_cents`, and is recomputed on every deposit and on every disbursement approval, rejection, and release. This balance must never go negative; any transition whose effect would drive `available_cents` below zero is rejected rather than allowed to breach the invariant.

### 2.10. Cascading Consequences and Automatic State Changes

Certain operations mutate more than one entity to keep the arrangement internally consistent, and the server performs these secondary changes on its own without a separate client request. Voiding a match voids the linked contract, and voiding a contract freezes the linked open escrow account, so a single void can propagate from match to contract to escrow. Terminating a journey freezes its open escrow account. In each such cascade, every entity the server touches has its own `updated_at` refreshed and its own `version` incremented, exactly as a direct mutation would. The precise preconditions and hops of each cascade are described in the workflow narratives of §3.

### 2.11. The Logical Clock

Time-sensitive rules — the contract cooling-off window and milestone achievement timestamps — read a server-controlled logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to real time. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the new `current_utc`; this is what allows cooling-off windows to be exercised deterministically.

## 3. Business Logic & Workflows

### 3.1. Intended-Parent and Carrier Intake and Screening

An arrangement begins with applicants. A `CaseManager` registers an **intended parent** by supplying a `legal_name`, a two-letter uppercase US `state_code` of residence, and a `budget_cents` figure (zero or greater) representing the total the intended parent will deposit into escrow. The record is created in `DRAFT` intake status with psychological clearance `PENDING`. Submitting an intended parent advances `intake_status` from `DRAFT` to `SUBMITTED`, and requires that `budget_cents` be zero or greater and a `legal_name` be present. A submitted intended parent may be bounced back for corrections, moving `SUBMITTED` back to `DRAFT`; this revision loop requires the record to currently be in `SUBMITTED`. A `Screener` moves a submitted record from `SUBMITTED` to `SCREENING`. During screening the `Screener` records the psychological outcome, setting `psych_clearance` to `PASSED` or `FAILED`; recording this outcome imposes no `intake_status` precondition and is accepted whatever state the record is in. Clearing an intended parent advances `SCREENING` to `CLEARED`, and requires the record to currently be in `SCREENING` and its `psych_clearance` to be `PASSED`; when the record is in `SCREENING` but its `psych_clearance` is not `PASSED`, clearing is rejected with `ERR_PSYCH_CLEARANCE_MISSING`. Alternatively a screening record may be rejected, moving `SCREENING` to `REJECTED`, which is terminal; rejection requires the record to be in `SCREENING`.

A **gestational carrier** is registered by a `CaseManager` with a `legal_name`, a two-letter uppercase `state_code` (the state where the carrier will deliver, which drives insurance review), a `prior_deliveries` count (zero or greater) of prior successful deliveries, and an agreed `base_compensation_cents` figure (zero or greater). The carrier is created in `DRAFT` with `psych_clearance` `PENDING`. Submitting a carrier advances `DRAFT` to `SUBMITTED`, but only if `prior_deliveries` is at least 1 and `base_compensation_cents` is zero or greater; a carrier whose `prior_deliveries` is below 1 is rejected with `ERR_CARRIER_INELIGIBLE`, and a count of exactly 1 passes. Starting screening moves `SUBMITTED` to `SCREENING`. A `Screener` sets the carrier's `psych_clearance` to `PASSED` or `FAILED`; this set imposes no `intake_status` precondition and is accepted whatever state the record is in. Clearing a carrier advances `SCREENING` to `CLEARED`, and this transition carries three requirements: the carrier is currently in `SCREENING`, its `psych_clearance` is `PASSED`, and an insurance review exists for this carrier whose status is either `APPROVED` or `GAP_IDENTIFIED`. If no such qualifying insurance review exists, clearing is rejected with `ERR_INSURANCE_REVIEW_REQUIRED`. A carrier in screening may instead be rejected, moving `SCREENING` to `REJECTED` (terminal), which requires the record to be in `SCREENING`.

### 3.2. Egg-Donor Intake and Insurance Review

An **egg donor** is optional to an arrangement and is registered by a `CaseManager` with a `donor_code` (an anonymized code), a two-letter uppercase `state_code`, and an agreed `donor_compensation_cents` figure (zero or greater). The donor is created in `DRAFT` intake status. Submitting a donor advances `DRAFT` to `SUBMITTED`, but only if the `donor_code` is unique among all donors that are not in a terminal state — that is, no other donor whose `intake_status` is `SUBMITTED`, `SCREENING`, or `CLEARED` already uses that code. A colliding `donor_code` is rejected with `ERR_CARRIER_INELIGIBLE`. A `Screener` starts screening, moving `SUBMITTED` to `SCREENING`, may clear the donor by moving `SCREENING` to `CLEARED`, or may reject the donor by moving `SCREENING` to `REJECTED` (terminal); each of the last three transitions requires the donor to be in the state that immediately precedes it.

Insurance adequacy for a carrier is assessed through an **insurance review**. A `Screener` creates one against a carrier by supplying the `carrier_id` and a `policy_kind` of `SURROGACY_FRIENDLY`, `EXCLUSION`, or `NONE`; the review is created in `PENDING` status. From `PENDING` the `Screener` reaches one of three terminal-of-intent outcomes based on the coverage presented. If `policy_kind` is `SURROGACY_FRIENDLY`, the review may be approved, moving `PENDING` to `APPROVED`. If `policy_kind` is `EXCLUSION`, the review may be moved from `PENDING` to `GAP_IDENTIFIED`, and this transition computes the supplemental-policy premium into `gap_premium_cents`. If `policy_kind` is `NONE`, the review may be moved from `PENDING` to `REJECTED`. Each outcome requires the review to currently be `PENDING` and its `policy_kind` to match the outcome as described; a review that is not `PENDING`, or whose `policy_kind` does not match the requested outcome, is rejected with `ERR_INVALID_STATE`.

The gap premium is derived from the carrier's own `base_compensation_cents`. First, a monthly figure is computed as `base_compensation_cents` multiplied by a monthly gap rate of 0.015, and that monthly figure is rounded half up to a whole number of cents. Then `gap_premium_cents` is that rounded monthly figure multiplied by 9 months. The rounding is applied to the monthly figure before the multiplication by 9, not after; rounding the total instead of the per-month figure could differ by as much as 8 cents, so the pinned order matters.

### 3.3. Matching Negotiation

A `CaseManager` proposes a **match** linking one intended parent and one carrier, optionally with an egg donor, by supplying `intended_parent_id`, `carrier_id`, an optional `donor_id` (left absent when the intended parent uses their own gametes, in which case it defaults to null), and the `proposed_carrier_comp_cents` offered in the opening round. The match is created in `PROPOSED` status with `offer_round` at 0.

Negotiation cycles between two states. A `CaseManager` may counter a proposal, moving `PROPOSED` to `COUNTERED`; this requires the match to be in `PROPOSED` and `expected_match_version` to equal the match's current `version`, and it sets `proposed_carrier_comp_cents` to the countered amount and increments the match `version`. From `COUNTERED`, a re-propose moves back to `PROPOSED`; it requires the match to be in `COUNTERED` and `expected_match_version` to match, and it increments `offer_round` by 1, sets `proposed_carrier_comp_cents` to the re-proposed amount, and increments the match `version`. This `PROPOSED → COUNTERED → PROPOSED` loop may repeat, with `offer_round` climbing by one on each re-propose.

Accepting a match moves `PROPOSED` to `ACCEPTED`. Acceptance requires that the match currently be `PROPOSED`, that `expected_match_version` equal the current `version`, and that every party be cleared: the linked intended parent's `intake_status` is `CLEARED`, the linked carrier's `intake_status` is `CLEARED`, and — only when a `donor_id` is present — the linked egg donor's `intake_status` is `CLEARED`. If any required party is not cleared, acceptance is rejected with `ERR_PSYCH_CLEARANCE_MISSING`. On acceptance, the carrier's `base_compensation_cents` is set to the match's `proposed_carrier_comp_cents`, and the match `version` increments. Once accepted, a `Screener` performs the match-level psychological clearance, moving `ACCEPTED` to `PSYCH_CLEARED`; this requires the match to be `ACCEPTED` and both the intended parent's and the carrier's `psych_clearance` to be `PASSED`, failing otherwise with `ERR_PSYCH_CLEARANCE_MISSING`. A match may be voided from any of `PROPOSED`, `COUNTERED`, `ACCEPTED`, or `PSYCH_CLEARED`, moving it to the terminal `VOID`; voiding begins the cascade described in §3.4.

Independently, the agreed carrier compensation can be inspected as a breakdown. The **carrier total compensation** starts from a base equal to the match's `proposed_carrier_comp_cents`. An experience bonus is layered on according to the carrier's `prior_deliveries`: when `prior_deliveries` is exactly 1 the bonus is 0; when `prior_deliveries` is 2 or 3 the bonus is the base multiplied by 0.05, rounded half up to whole cents; when `prior_deliveries` is 4 or more the bonus is the base multiplied by 0.10, rounded half up to whole cents. A multiples add-on of 500,000 cents applies when any milestone of type `HEARTBEAT` on the journey is `ACHIEVED` and the journey's `current_phase` is `HEARTBEAT_CONFIRMED` or later (that is, `HEARTBEAT_CONFIRMED` or `BORN`); otherwise the add-on is 0. The evaluation order is pinned: the experience bonus is computed from the base and rounded first, and only then are the base, the experience bonus, and the multiples add-on summed to give the total. The breakdown read exposes `base_cents`, `experience_bonus_cents`, `multiples_addon_cents`, and `total_cents`.

### 3.4. Contract Execution and the Void Cascade

Once a match reaches `PSYCH_CLEARED`, a `CaseManager` drafts a gestational-carrier **contract** for it by supplying the `match_id`; the contract is created in `DRAFTED` status. Drafting itself imposes no status precondition on the referenced match — the `match_id` need only resolve to an existing match — and the `PSYCH_CLEARED` requirement is instead enforced downstream at IP signing. The intended parent, acting as `IntendedParentActor`, signs first: signing moves `DRAFTED` to `IP_SIGNED`, requires the contract to be `DRAFTED` and the linked match to be `PSYCH_CLEARED`, and stamps `ip_signed_at` with the current logical-clock time. That signature starts a mandatory reflection window of `cooling_off_days`, which is 3 days. The carrier, acting as `CarrierActor`, counter-signs to move `IP_SIGNED` to `EXECUTED`; this requires the contract to be `IP_SIGNED` and the current clock time to be at or after `ip_signed_at` plus `cooling_off_days`. A counter-signature attempted before that window has fully elapsed is rejected with `ERR_COOLING_OFF_ACTIVE`.

A contract may be voided from either `DRAFTED` or `IP_SIGNED`, moving it to the terminal `VOID`; voiding requires the contract's status to be `DRAFTED` or `IP_SIGNED`. When a contract is voided — whether directly by a `CaseManager` or as a cascade from a match void — if an escrow account exists for the linked journey and is currently `OPEN`, that account is moved to `FROZEN`. This is the second hop of the void cascade: voiding a match, from any of its non-terminal states, first transitions the match's linked contract to `VOID` if such a contract exists and is not already `VOID` (hop one), which in turn freezes the open escrow account of the linked journey (hop two). Every entity touched along the way has its `version` incremented.

### 3.5. Journey Start and Escrow Funding

A `CaseManager` starts a **journey** from a match by supplying the `match_id`. A journey may only be started from a match that is `PSYCH_CLEARED` and whose contract is `EXECUTED`; an attempt from a match that does not meet both conditions is rejected with `ERR_JOURNEY_PRECONDITION`. Creating the journey puts it in `ACTIVE` status, sets its computed `current_phase` to `PRE_TRANSFER` and its `parentage_order_status` to `NOT_FILED`, and — as an automatic cascade — opens a companion **escrow account** for this journey, in `OPEN` status, whose `journey_id` points back at the journey. The escrow account's `deposited_cents`, `disbursed_cents`, and `reserved_cents` all begin at 0, and its `available_cents` is therefore 0.

The intended parent, acting as `IntendedParentActor`, funds the arrangement by depositing into the escrow account. A deposit supplies an `amount_cents` and the `expected_escrow_version`. It requires the account to be `OPEN` and, as described in §2.7, the supplied `expected_escrow_version` to equal the account's current `version`. The deposit is also capped by the intended parent's budget: the account's `deposited_cents` plus the new `amount_cents` must not exceed the linked intended parent's `budget_cents`. A deposit that would push cumulative `deposited_cents` above `budget_cents` is rejected with `ERR_BUDGET_EXCEEDED`. On success the `amount_cents` is added to `deposited_cents`, `available_cents` is recomputed, and the account `version` increments.

A journey's overall progress is gated by milestones and can be paused. A `CaseManager` may place an `ACTIVE` journey `ON_HOLD` and later resume it from `ON_HOLD` back to `ACTIVE`; the hold requires the journey to be `ACTIVE` and the resume requires it to be `ON_HOLD`. A journey may be terminated from either `ACTIVE` or `ON_HOLD`, moving it to the terminal `TERMINATED`; termination freezes the linked escrow account if it is open. Completing a journey moves `ACTIVE` to the terminal `COMPLETED`, but only when the journey is `ACTIVE`, a milestone of type `BIRTH` exists on it with status `ACHIEVED`, and its `parentage_order_status` is `GRANTED`; if the journey is not `ACTIVE`, the `BIRTH` milestone is not `ACHIEVED`, or the parentage order is not `GRANTED`, the request is rejected with `ERR_INVALID_STATE`.

### 3.6. Clinical Milestones and Parentage

Within a journey, a `CaseManager` schedules **milestones**. A milestone is created with a `milestone_type` of `EMBRYO_TRANSFER`, `HEARTBEAT`, or `BIRTH`, and a `scheduled_utc` clinical date-time (ISO 8601 UTC); it begins in `SCHEDULED` status with `achieved_utc` unset. At most one milestone of each `milestone_type` may exist per journey; a second milestone of a type already present is rejected with `ERR_DUPLICATE_MILESTONE`.

Confirming a milestone moves `SCHEDULED` to the terminal `ACHIEVED`. Achievement requires the milestone to be `SCHEDULED` and the journey to be `ACTIVE`, and it enforces clinical ordering: a `HEARTBEAT` milestone may be achieved only if this journey's `EMBRYO_TRANSFER` milestone is already `ACHIEVED`, and a `BIRTH` milestone may be achieved only if this journey's `HEARTBEAT` milestone is already `ACHIEVED`. An out-of-order achievement is rejected with `ERR_MILESTONE_ORDER_VIOLATION`. On achievement the system stamps `achieved_utc` with the current logical-clock time and recomputes the journey's `current_phase` from its achieved milestones — the phase advances along `PRE_TRANSFER`, then `TRANSFERRED` once `EMBRYO_TRANSFER` is achieved, then `HEARTBEAT_CONFIRMED` once `HEARTBEAT` is achieved, then `BORN` once `BIRTH` is achieved. A milestone may instead be failed, moving `SCHEDULED` to the terminal `FAILED`, which requires it to be `SCHEDULED`.

The legal parentage order is tracked on the journey through `parentage_order_status`. A `CaseManager` files the pre-birth order, moving it from `NOT_FILED` to `FILED`; filing when the order is not currently `NOT_FILED` is rejected with `ERR_INVALID_STATE`. Filing is blocked when the linked intended parent's `state_code` is a parentage-hostile jurisdiction — specifically `LA` or `NE` — because those states forbid pre-birth orders; an attempt in such a state is rejected with `ERR_PARENTAGE_JURISDICTION_BLOCKED`. Once filed, the `CaseManager` records the court's outcome by supplying a `decision`, which moves `FILED` to either `GRANTED` or `DENIED`; recording a decision when the order is not currently `FILED` is rejected with `ERR_INVALID_STATE`, and a `decision` value that is neither `GRANTED` nor `DENIED` is rejected as a malformed request with `ERR_INVALID_REQUEST`.

### 3.7. Compensation Schedule and the Two Escrow Projections

Payments to the carrier and donor are laid out as a **compensation schedule** on the journey. A `CaseManager` or `FinanceOfficer` adds a schedule line by supplying a `trigger_milestone_type` (`EMBRYO_TRANSFER`, `HEARTBEAT`, or `BIRTH`) identifying which achieved milestone unlocks the payment, a `recipient` of `CARRIER` or `DONOR`, and an `amount_cents` (zero or greater).

The escrow summary read reports the account's `available_cents` alongside two deliberately different projections computed from the same schedule data. The first, the **disbursable-now** amount, answers what could be paid right this moment. It considers only those schedule lines whose `trigger_milestone_type` corresponds to a milestone already `ACHIEVED` on the journey. It walks the achieved milestones in order of their `achieved_utc` ascending, breaking ties by `created_at` ascending, and within each milestone walks the matching schedule lines in `created_at` ascending order. It keeps a running total, and for each candidate line it adds that line's `amount_cents` to the running total only if doing so would keep the running total at or below `available_cents`; a line that would push the running total above `available_cents` is skipped, but the walk does not stop there — it continues in the same strict order and still admits any later line that individually fits within the remaining headroom. The result is reported as `disbursable_now_cents`.

The second projection, the **projected liability**, is the forward-looking dual of the first and ignores both the ordering and the `available_cents` cap. It sums the `amount_cents` of every schedule line on the journey whose trigger milestone is not `FAILED` — that is, whose corresponding milestone is either scheduled or already achieved — including milestones not yet reached; a line whose trigger milestone type has not yet been scheduled on the journey at all (no such milestone record exists) is likewise treated as not-`FAILED` and included in the sum. This total is reported as `projected_liability_cents`. From it, a funding shortfall is derived as the projected liability minus `available_cents`, floored at 0 so it is never negative, and reported as `funding_shortfall_cents`.

### 3.8. Disbursement Approval and Release

Actual payouts flow through **disbursements**, each drawn from an escrow account against a specific schedule line. A `CaseManager` or `FinanceOfficer` requests a disbursement on a journey by supplying the `schedule_id` of the schedule line to pay and the `escrow_account_id` to draw from; the disbursement is created in `REQUESTED` status, and its `amount_cents` is copied from the referenced compensation-schedule line at approval time.

A `CaseManager` approves a requested disbursement, moving `REQUESTED` to `APPROVED`. Approval requires the disbursement to be `REQUESTED`, the schedule line's `trigger_milestone_type` to have a corresponding `ACHIEVED` milestone on this journey, and the escrow account to be `OPEN`. If the trigger milestone has not been achieved, approval is rejected with `ERR_MILESTONE_GATE_NOT_MET`. Approval also enforces fiscal sufficiency: the disbursement's `amount_cents` must be at or below the escrow account's `available_cents`; an amount exceeding available funds is rejected with `ERR_INSUFFICIENT_ESCROW`. On approval the system records the acting `CaseManager`'s `X-User-ID` as `approved_by_user_id`, adds `amount_cents` to the account's `reserved_cents`, recomputes `available_cents` (reserving reduces available funds but leaves `deposited_cents` untouched), and increments both the escrow account's `version` and the disbursement's `version`.

A `FinanceOfficer` then releases an approved disbursement, moving `APPROVED` to the terminal `RELEASED`. Release requires the disbursement to be `APPROVED`, the escrow account to be `OPEN`, and — per the segregation-of-duties rule in §2.8 — the acting officer's `X-User-ID` to differ from the recorded `approved_by_user_id`, failing otherwise with `ERR_SEGREGATION_OF_DUTIES`. On release the system moves `amount_cents` from `reserved_cents` into `disbursed_cents`, recomputes `available_cents`, and increments both the escrow and disbursement `version` counters; `reserved_cents` decreases and `disbursed_cents` increases by the same amount while `deposited_cents` is unchanged.

A disbursement may be rejected instead. Rejecting a `REQUESTED` disbursement moves it to the terminal `REJECTED` with no escrow effect. Rejecting an `APPROVED` disbursement also moves it to `REJECTED` but first releases its reservation: it subtracts `amount_cents` from the account's `reserved_cents`, recomputes `available_cents`, and increments the escrow and disbursement `version` counters — returning the previously reserved funds to available. Rejection from `REQUESTED` requires the disbursement to be `REQUESTED`, and rejection from `APPROVED` requires it to be `APPROVED`.

### 3.9. Escrow Freezing, Unfreezing, and Closing

Beyond the automatic freezes triggered by contract voids and journey terminations, a `FinanceOfficer` may directly manage an escrow account's lifecycle. Freezing moves an `OPEN` account to `FROZEN` and requires it to be `OPEN`. Unfreezing moves a `FROZEN` account back to `OPEN`, but only if the account is `FROZEN` and the linked contract's status is not `VOID`; a frozen account whose contract has been voided cannot be reopened, because the condition that froze it has not been reversed, and the attempt is rejected with `ERR_INVALID_STATE`. Closing moves an `OPEN` account to the terminal `CLOSED` and requires the account to be `OPEN`, its `reserved_cents` to be exactly 0, and the linked journey's status to be `COMPLETED`; a close attempt that fails any of these three conditions is rejected with `ERR_INVALID_STATE`.

### 3.10. Validation Ordering

When several checks could reject one request, they are evaluated in a fixed priority order so the returned error is deterministic. Authentication comes first: a request missing valid headers fails with `ERR_UNAUTHENTICATED` before anything else. Authorization is next: a role not permitted for the operation fails with `ERR_FORBIDDEN`. Existence follows: path identifiers (left to right) and then body foreign keys are resolved, and a missing one yields `ERR_NOT_FOUND`. State validity is then checked: a resource not in a valid state for the requested transition fails with `ERR_INVALID_STATE`. After these come the business rules — psychological-clearance gates (`ERR_PSYCH_CLEARANCE_MISSING`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), carrier eligibility and donor-code uniqueness (`ERR_CARRIER_INELIGIBLE`), the insurance-review requirement for carrier clearance (`ERR_INSURANCE_REVIEW_REQUIRED`), parentage jurisdiction (`ERR_PARENTAGE_JURISDICTION_BLOCKED`), the cooling-off window (`ERR_COOLING_OFF_ACTIVE`), milestone ordering (`ERR_MILESTONE_ORDER_VIOLATION`), milestone-type uniqueness (`ERR_DUPLICATE_MILESTONE`), the budget cap (`ERR_BUDGET_EXCEEDED`), and escrow sufficiency (`ERR_INSUFFICIENT_ESCROW`). The optimistic-concurrency check (`ERR_STALE_VERSION`) is evaluated in the state category, after existence and basic state validity. A malformed body — a missing required field, an invalid enum, negative cents, or a bad `decision` value — is reported as `ERR_INVALID_REQUEST`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including state transitions and computed reads, return `200 OK`. The full request payload, response body, and side effects of each endpoint are described in the §3 narratives above; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/intended-parents` | Create an intended-parent applicant in DRAFT | CaseManager |
| GET | `/intended-parents/{id}` | Fetch an intended parent | CaseManager, Screener, FinanceOfficer |
| GET | `/intended-parents` | List intended parents (filterable by intake_status) | CaseManager, Screener, FinanceOfficer |
| POST | `/intended-parents/{id}/submit` | Submit for screening | CaseManager |
| POST | `/intended-parents/{id}/return-to-draft` | Return a submitted applicant to draft | CaseManager |
| POST | `/intended-parents/{id}/start-screening` | Begin screening | Screener |
| POST | `/intended-parents/{id}/set-psych` | Record psychological clearance outcome | Screener |
| POST | `/intended-parents/{id}/clear` | Clear (requires psych PASSED) | Screener |
| POST | `/intended-parents/{id}/reject` | Reject | Screener |
| POST | `/carriers` | Create a gestational-carrier applicant in DRAFT | CaseManager |
| GET | `/carriers/{id}` | Fetch a carrier | CaseManager, Screener, FinanceOfficer |
| GET | `/carriers` | List carriers (filterable by intake_status) | CaseManager, Screener, FinanceOfficer |
| POST | `/carriers/{id}/submit` | Submit (requires prior_deliveries >= 1) | CaseManager |
| POST | `/carriers/{id}/start-screening` | Begin screening | Screener |
| POST | `/carriers/{id}/set-psych` | Record psychological clearance outcome | Screener |
| POST | `/carriers/{id}/clear` | Clear (requires psych PASSED + insurance review) | Screener |
| POST | `/carriers/{id}/reject` | Reject | Screener |
| GET | `/carriers/{id}/insurance-reviews` | List insurance reviews for a carrier | CaseManager, Screener, FinanceOfficer |
| POST | `/egg-donors` | Create an egg-donor applicant in DRAFT | CaseManager |
| GET | `/egg-donors/{id}` | Fetch an egg donor | CaseManager, Screener, FinanceOfficer |
| GET | `/egg-donors` | List egg donors (filterable by intake_status) | CaseManager, Screener, FinanceOfficer |
| POST | `/egg-donors/{id}/submit` | Submit (donor_code uniqueness among non-terminal donors) | CaseManager |
| POST | `/egg-donors/{id}/start-screening` | Begin screening | Screener |
| POST | `/egg-donors/{id}/clear` | Clear | Screener |
| POST | `/egg-donors/{id}/reject` | Reject | Screener |
| POST | `/insurance-reviews` | Create an insurance review for a carrier in PENDING | Screener |
| GET | `/insurance-reviews/{id}` | Fetch an insurance review | CaseManager, Screener, FinanceOfficer |
| POST | `/insurance-reviews/{id}/approve` | Approve (requires SURROGACY_FRIENDLY) | Screener |
| POST | `/insurance-reviews/{id}/identify-gap` | Identify gap (computes gap_premium_cents) | Screener |
| POST | `/insurance-reviews/{id}/reject` | Reject (policy_kind NONE) | Screener |
| POST | `/matches` | Propose a match (IP + carrier + optional donor) | CaseManager |
| GET | `/matches/{id}` | Fetch a match | CaseManager, Screener, FinanceOfficer |
| GET | `/matches` | List matches (filterable by intended_parent_id, carrier_id, donor_id, status) | CaseManager, Screener, FinanceOfficer |
| GET | `/matches/{id}/comp-breakdown` | Carrier total-compensation breakdown | CaseManager, FinanceOfficer |
| POST | `/matches/{id}/counter` | Counter the current offer | CaseManager |
| POST | `/matches/{id}/re-propose` | Re-propose after a counter | CaseManager |
| POST | `/matches/{id}/accept` | Accept (requires all parties CLEARED) | CaseManager |
| POST | `/matches/{id}/psych-clear` | Match-level psych clearance | Screener |
| POST | `/matches/{id}/void` | Void the match (cascades to contract, then escrow) | CaseManager |
| POST | `/contracts` | Draft a contract for a psych-cleared match | CaseManager |
| GET | `/contracts/{id}` | Fetch a contract | CaseManager, Screener, FinanceOfficer, IntendedParentActor, CarrierActor |
| GET | `/contracts` | List contracts (filterable by match_id, status) | CaseManager, Screener, FinanceOfficer |
| POST | `/contracts/{id}/ip-sign` | IP signs (stamps ip_signed_at, starts cooling-off) | IntendedParentActor |
| POST | `/contracts/{id}/carrier-sign` | Carrier counter-signs (requires cooling-off elapsed) | CarrierActor |
| POST | `/contracts/{id}/void` | Void the contract (freezes linked escrow) | CaseManager |
| POST | `/journeys` | Start a journey (auto-opens an escrow account) | CaseManager |
| GET | `/journeys/{id}` | Fetch a journey (includes computed current_phase) | CaseManager, Screener, FinanceOfficer |
| GET | `/journeys` | List journeys (filterable by match_id, status) | CaseManager, Screener, FinanceOfficer |
| POST | `/journeys/{id}/hold` | Place journey on hold | CaseManager |
| POST | `/journeys/{id}/resume` | Resume journey | CaseManager |
| POST | `/journeys/{id}/complete` | Complete (requires BIRTH ACHIEVED + parentage GRANTED) | CaseManager |
| POST | `/journeys/{id}/terminate` | Terminate (freezes linked escrow) | CaseManager |
| POST | `/journeys/{id}/parentage/file` | File pre-birth parentage order | CaseManager |
| POST | `/journeys/{id}/parentage/decide` | Record parentage decision (GRANTED or DENIED) | CaseManager |
| POST | `/journeys/{id}/milestones` | Schedule a milestone (type uniqueness enforced) | CaseManager |
| GET | `/journeys/{id}/milestones` | List milestones for a journey | CaseManager, Screener, FinanceOfficer |
| POST | `/journeys/{id}/milestones/{mid}/achieve` | Achieve a milestone (ordering enforced) | CaseManager |
| POST | `/journeys/{id}/milestones/{mid}/fail` | Fail a milestone | CaseManager |
| POST | `/journeys/{id}/comp-schedule` | Add a compensation-schedule line | CaseManager, FinanceOfficer |
| GET | `/journeys/{id}/comp-schedule` | List compensation-schedule lines for a journey | CaseManager, FinanceOfficer |
| GET | `/escrow-accounts/{id}` | Fetch an escrow account (includes computed available_cents) | CaseManager, FinanceOfficer |
| GET | `/escrow-accounts` | List escrow accounts (filterable by journey_id) | CaseManager, FinanceOfficer |
| GET | `/escrow-accounts/{id}/summary` | Disbursable-now, projected-liability, funding-shortfall summary | CaseManager, FinanceOfficer |
| POST | `/escrow-accounts/{id}/deposit` | IP deposits funds (OCC; budget cap) | IntendedParentActor |
| POST | `/escrow-accounts/{id}/freeze` | Freeze an open account | FinanceOfficer |
| POST | `/escrow-accounts/{id}/unfreeze` | Unfreeze (blocked if linked contract VOID) | FinanceOfficer |
| POST | `/escrow-accounts/{id}/close` | Close (reserved must be 0, journey COMPLETED) | FinanceOfficer |
| POST | `/journeys/{id}/disbursements` | Request a disbursement against a schedule line | CaseManager, FinanceOfficer |
| GET | `/journeys/{id}/disbursements` | List disbursements for a journey | CaseManager, FinanceOfficer |
| POST | `/journeys/{id}/disbursements/{did}/approve` | Approve (reserves funds; records approver) | CaseManager |
| POST | `/journeys/{id}/disbursements/{did}/release` | Release (releaser must differ from approver) | FinanceOfficer |
| POST | `/journeys/{id}/disbursements/{did}/reject` | Reject (returns any reservation) | CaseManager |
| GET | `/disbursements/{id}` | Fetch a single disbursement | CaseManager, FinanceOfficer |
| GET | `/disbursements` | List disbursements (filterable by journey_id, schedule_id, escrow_account_id) | CaseManager, FinanceOfficer |
| GET | `/comp-schedule/{id}` | Fetch a single compensation-schedule line | CaseManager, FinanceOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | CaseManager, FinanceOfficer, Screener |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CARRIER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PSYCH_CLEARANCE_MISSING` | 422 Unprocessable Entity |
| `ERR_INSURANCE_REVIEW_REQUIRED` | 422 Unprocessable Entity |
| `ERR_COOLING_OFF_ACTIVE` | 422 Unprocessable Entity |
| `ERR_MILESTONE_ORDER_VIOLATION` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_MILESTONE` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_ESCROW` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_PARENTAGE_JURISDICTION_BLOCKED` | 422 Unprocessable Entity |
| `ERR_MILESTONE_GATE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_JOURNEY_PRECONDITION` | 422 Unprocessable Entity |
| `ERR_VALIDATION_LIMIT` | 422 Unprocessable Entity |
</content>
</invoke>
