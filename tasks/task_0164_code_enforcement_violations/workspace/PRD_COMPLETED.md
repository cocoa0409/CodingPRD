# Code Enforcement & Violations API — Product Requirements Document

## 1. Introduction

Municipalities run a long, branching enforcement pipeline every time a property falls out of code: a complaint arrives, an inspector confirms it, a violation notice is cited against the owner, a cure window opens, fines accrue daily once the deadline passes, the owner may contest before a hearing officer, abatement crews board up or demolish derelict structures, and unpaid penalties ultimately ripen into a recorded lien against the parcel. This API is the system of record for that pipeline. It models the full chain of custody from intake through settlement, holding the line on who may act, when an action is legally ripe, and exactly how much money is owed at any instant.

The hard problems this system solves are temporal and fiscal. Fines are time-sensitive — they grow with every whole day a notice sits overdue, freeze the moment compliance is verified or an appeal is decided, and must reconcile to the cent when a lien is recorded. Repeat offenders pay escalated penalties, so the system tracks each owner's recent violation history and freezes a multiplier onto every new citation. Because liens encumber real property and reflect a frozen money figure, the act of recording one is guarded by optimistic concurrency: a clerk who computes a lien against a stale view of the case must be turned away rather than allowed to record a wrong principal. The remainder of this document specifies the entities, lifecycles, calculations, and guard rails that make this enforcement ledger trustworthy.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. Authentication is driven solely by `X-User-Role`: a request that omits `X-User-Role` or presents a value that is not one of the recognized roles is rejected with `ERR_UNAUTHENTICATED`, while a missing `X-User-ID` is not by itself an authentication failure (it surfaces only later, where an operation actually consults the acting identity — for example a registrant ownership check). When the header is well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes five roles: `PlatformAdmin`, `CodeOfficer`, `HearingOfficer`, `FinanceClerk`, and `Registrant`.

Four of these roles carry an opaque identity. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform admin seeds fee schedules, drives the clock, and registers owners and properties. When `X-User-Role` is `CodeOfficer`, `X-User-ID` is likewise an opaque operator identifier; the server records it where a transition writes it — for example, as `opened_by_user_id` on the `Case` that the officer opens, or as `requested_by_user_id` on a `Reinspection` the officer schedules — but it is never compared to any entity's `id` for ownership. When `X-User-Role` is `HearingOfficer`, `X-User-ID` is an opaque adjudicator identifier, recorded where applicable but not matched against any entity. When `X-User-Role` is `FinanceClerk`, `X-User-ID` is an opaque fiscal-officer identifier, again recorded but not ownership-checked.

The `Registrant` role is different: it is entity-backed. When `X-User-Role` is `Registrant`, `X-User-ID` is the `id` of the acting `Owner`. Ownership checks on any resource that references an `Owner` compare the resource's owner foreign key to `X-User-ID`. Concretely, when a registrant contests a notice, the system resolves the notice's case, then the case's property, and confirms that the property's owner-of-record equals the acting `X-User-ID`; a mismatch is rejected with `ERR_NOT_NOTICE_OWNER`. The `requested_by_user_id` recorded on a `Hearing` is the `Owner.id` of the registrant who filed the appeal.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0. Out-of-range numeric values are clamped to their nearest bound rather than rejected — a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0 — while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system are full first-class records. Owners, properties, cases, complaints, inspections, violation notices, re-inspections, fines, hearings, abatement orders, and liens each carry a system-minted `id` formatted as a UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC values rendered with three fractional digits. The `version` begins at `1` on creation and increments by one on every mutation of the resource; `updated_at` is refreshed to the mutation instant whenever the resource changes.

The one exception is the `FeeSchedule`. A fee schedule is reference configuration and carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. Do not expose those two fields on fee-schedule responses.

This system runs on a server-controlled logical clock rather than wall time. A platform-admin test-driving capability sets the server's current UTC instant to a supplied `to_iso8601` value, and the response reports the resulting `current_utc`. Every time-sensitive evaluation in the system — overdue detection, daily fine accrual, contest windows, hearing ripeness, foreclosure waiting periods, and the rolling repeat-offender window — reads this logical clock, never the host wall clock.

### 2.5. Compound Case Posture and Hierarchical Recomputation

A `Case` is the aggregate root of an enforcement matter, but its `posture` is never set directly. It is a computed, compound value recomputed after every child mutation — complaint triage, notice issuance or resolution, abatement ordering, lien recording or release, payment posting, and case close. The recomputation evaluates five conditions in strict priority order and stops at the first that holds: the case is `CLOSED` if `closed_at` is set; otherwise `LIENED` if any `Lien` for the case is in `RECORDED` status; otherwise `ABATEMENT` if any `AbatementOrder` for the case is in either `ORDERED` or `IN_PROGRESS` status; otherwise `ACTIVE` if any `ViolationNotice` for the case is in `ISSUED`, `OVERDUE`, `CONTESTED`, or `UPHELD` status; otherwise `INTAKE`. A newly opened case starts at `INTAKE`, and `CLOSED` is the only terminal posture.

Because posture and balances derive from children, many client-visible state changes happen without a direct request on the case. When a notice is issued, contested, upheld, dismissed, or settled, when an abatement order is placed or completed, and when a lien is recorded or released, the system recomputes the parent case's `posture` and its `outstanding_balance_cents`, and each such reconciliation independently mutates the case — bumping its `version` and refreshing `updated_at`. Reads are also live: fetching a case recomputes its posture and its provisional outstanding balance against the current clock before responding, and fetching a notice lazily evaluates whether it has crossed into `OVERDUE` and recomputes its provisional fine before responding.

### 2.6. Money, Precision, and Rounding

All monetary amounts are stored and returned as integer cents. Fee-schedule figures, fine totals, payment amounts, lien principal, administrative fees, and case balances are all whole-cent integers; the API never returns fractional cents.

Two computed amounts involve a multiplication that can produce a fractional cent: the escalation-adjusted fine total and the lien's administrative fee. In both cases the product is rounded to the nearest whole cent using the round-half-up convention, and that rounding is applied exactly once to the final product — never per intermediate day and never to a running subtotal. The escalation multiplier itself is an exact decimal (`1.0`, `1.5`, or `2.0`) and the administrative-fee rate is an exact decimal (`0.05` or `0.10`); precision loss is confined to the single half-up rounding step on each product.

### 2.7. Optimistic Concurrency on Lien Recording

Recording a lien is the one operation in this system guarded by optimistic concurrency control, because a lien freezes a money figure derived from the case's current balance and that balance changes whenever a payment is posted or a fine is waived. A request to record a lien must carry `expected_case_version` as a non-optional field whose value is the client's last observed `version` of the target `Case`. If `expected_case_version` does not equal the case's current `version` at the moment of recording, the request is rejected with `ERR_STALE_VERSION` and HTTP status 412. This means that if any other writer has advanced the case's version since the client last read it — for instance by posting a payment or waiving a contested fine, each of which bumps `Case.version` and shifts the balance — the clerk's view is stale and the lien they would freeze could carry a wrong principal, so the record is refused. No other endpoint takes a version field; posting a payment also requires `expected_case_version` and is described with the payment workflow.

### 2.8. Nested Resource Retrieval and Reference Resolution

Several read endpoints address a child collection under a parent path, such as a case's complaints, a notice's re-inspections, a notice's fines, a notice's hearings, a case's abatement orders. For any path that carries more than one identifier, the system validates identifiers left-to-right and rejects the first one that does not resolve with `ERR_NOT_FOUND`; a child that exists but does not belong to the named parent is treated the same way. A single missing identifier always yields `ERR_NOT_FOUND` as well.

Foreign keys supplied in a request body are resolved before business rules run. When a create request names a parent or related resource — an `owner_id`, a `property_id`, a `case_id`, a `source_inspection_id`, or a `notice_id` — and that reference does not resolve to an existing record, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Finally, any request body missing a required field, or supplying an enum value outside its permitted set, is rejected with `ERR_INVALID_REQUEST`.

### 2.9. Validation Ordering

When several checks could fail on the same request, they are evaluated in a fixed precedence so the returned error is deterministic. Authentication comes first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization is next: a recognized role that is not permitted for the operation yields `ERR_FORBIDDEN`. Path-identifier existence is third, yielding `ERR_NOT_FOUND` for any unresolved or mis-parented path id. The registrant ownership check on a contest is next, yielding `ERR_NOT_NOTICE_OWNER`. Body foreign-key resolution follows, yielding `ERR_REFERENCE_NOT_FOUND`. State-machine legality is then checked: a transition requested from a state where it is not defined yields `ERR_INVALID_STATE`. Only after all of these pass does the system evaluate the operation's own business constraints (substantiation, fee-schedule presence, demolition eligibility, contest windows, hearing slots and ripeness, continuance limits, foreclosure ripeness, duplicate-lien, nothing-to-lien, optimistic concurrency, balance, missing actual cost, duplicate parcel, re-inspection target). The malformed-body check that yields `ERR_INVALID_REQUEST` guards every create and transition that takes a body.

## 3. Business Logic & Workflows

### 3.1. Configuration, Owners, and Properties

Before any enforcement can happen, a `PlatformAdmin` seeds the fee schedules that price citations. A `FeeSchedule` row is created for a single `violation_class` — one of `MINOR`, `MAJOR`, or `HAZARD` — and carries the `base_fine_cents` assessed at issuance, the `daily_accrual_cents` charged for each whole overdue day before any multiplier, the `max_total_cents` hard cap on the combined base-plus-accrual figure for a single notice, and `cure_days`, the number of whole days a cited owner has to fix the problem before overdue accrual begins. Fee schedules are read by admins, code officers, and finance clerks, optionally filtered by `violation_class`.

Owners are registered by a platform admin or a code officer with a `full_name` and a `mailing_email`; the email doubles as the registrant login identity. A freshly registered owner starts at `repeat_tier` of `FIRST` with a `prior_violation_count` of zero. Both of those fields are computed live whenever an owner is read, as described in the repeat-offender section below. Properties are likewise registered by a platform admin or a code officer, each naming the `owner_id` of record, a `parcel_number`, a `street_address`, and an `occupancy` of either `OCCUPIED` or `VACANT` that later governs demolition eligibility. A new property is `ACTIVE`; its `status` may otherwise be `ARCHIVED`. The `parcel_number` must be unique among non-`ARCHIVED` properties — an attempt to register a parcel number already held by an active property is rejected with `ERR_DUPLICATE_PARCEL`. Properties can be listed and filtered by `owner_id` for reverse lookup of an owner's parcels.

### 3.2. Opening a Case and the Single-Active-Case Rule

A `CodeOfficer` opens an enforcement `Case` against a parcel by supplying the `property_id`. The new case starts with `posture` of `INTAKE`, an `outstanding_balance_cents` of zero, `payments_applied_cents` of zero, and a null `closed_at`; the officer's opaque identifier is captured as `opened_by_user_id`. A parcel may host only one live enforcement matter at a time. Opening a case on a property that already has a case whose posture is anything other than `CLOSED` is rejected with `ERR_PROPERTY_HAS_OPEN_CASE`. This is an exclusive-occupancy rule with half-open interval semantics: a property is occupied by its case across the interval running from when the case opened up to but not including the instant the prior case reached `CLOSED`. Because the closing instant frees the parcel, a new case opened at or after the prior case's close is permitted — back-to-back cases are fine — but two open intervals may never overlap. Cases can be listed and filtered by `property_id`.

A case is finally closed by a `FinanceClerk` once the matter is fully resolved. Closing is defined from any non-`CLOSED` posture — `INTAKE`, `ACTIVE`, `ABATEMENT`, or `LIENED` — and no posture restriction is enforced beyond rejecting an already-closed case; the close imposes no minimum posture, so a quiescent zero-balance `INTAKE` case (one that never advanced past intake) may be closed directly. Closing requires two conditions: every `ViolationNotice` on the case must be in a benign terminal state — `COMPLIED`, `DISMISSED`, or `SETTLED` — and the case's `outstanding_balance_cents` must be exactly zero, meaning any lien has been released and any fines settled. Before either condition is evaluated, a case whose posture is already `CLOSED` is rejected with `ERR_INVALID_STATE`, since `CLOSED` is terminal and a case cannot be re-closed. These two conditions are then evaluated in a fixed order: the balance-zero condition is checked first, so if the balance is still nonzero the close is rejected with `ERR_BALANCE_OUTSTANDING`; only once the balance is exactly zero is the notice-status condition checked, and if any `ViolationNotice` on the case is not in a benign terminal state the close is rejected with `ERR_INVALID_STATE`. On a successful close the system stamps `closed_at` with the current clock and recomputes the posture, which lands on `CLOSED`.

### 3.3. Complaints and Inspections

A complaint is the usual trigger for a case. A `CodeOfficer` or a `Registrant` files a `Complaint` under an existing case by supplying the `case_id`, a `reporter_kind` of `RESIDENT`, `ANONYMOUS`, or `OFFICER_OBSERVED`, and a free-text `narrative`. A new complaint is `RECEIVED`. From there a code officer may triage it — moving it to `TRIAGED`, which is what enables an initial inspection to be scheduled — provided its `narrative` is present. Alternatively a code officer may dismiss a received complaint, moving it to `DISMISSED`, but only when no inspection with an outcome of `VIOLATION_FOUND` is linked to that complaint's case; a dismissal is otherwise blocked with `ERR_INVALID_STATE` because the case already has substantiated grounds. Both triage and dismiss are defined only from `RECEIVED`; attempting either against a complaint in any other status is likewise rejected with `ERR_INVALID_STATE`. `DISMISSED` is terminal for a complaint. A case's complaints can be listed as a sub-resource of the case.

Inspections do the field work. A `CodeOfficer` schedules an `Inspection` against a `case_id` with a `kind` of either `INITIAL` or `REINSPECTION`. An `INITIAL` inspection confirms a complaint and carries no notice reference; a `REINSPECTION` verifies compliance against a specific notice and must name the `notice_id` it targets. A re-inspection-kind inspection is only valid when its `notice_id` references a notice on the same case that is currently `ISSUED` or `OVERDUE`; otherwise the schedule is rejected with `ERR_REINSPECTION_TARGET_INVALID`. A `REINSPECTION` that omits `notice_id` entirely is treated as an invalid re-inspection target — `ERR_REINSPECTION_TARGET_INVALID`, not `ERR_INVALID_REQUEST` — whereas a supplied `notice_id` that resolves to no notice at all is rejected at foreign-key resolution with `ERR_REFERENCE_NOT_FOUND`. A new inspection's `outcome` is `PENDING` and its `inspected_on` is null. When the officer submits the inspection, the supplied `outcome` is recorded — one of `VIOLATION_FOUND`, `NO_VIOLATION`, `COMPLIANT`, or `NON_COMPLIANT` — and `inspected_on` is stamped with the current clock. A `VIOLATION_FOUND` outcome is what substantiates a subsequent citation. Inspections can be listed and filtered by `case_id` or by `notice_id`.

### 3.4. Issuing a Violation Notice and Freezing the Escalation Multiplier

A `CodeOfficer` issues a `ViolationNotice` by naming the `case_id`, the `source_inspection_id` that substantiates it, and the `violation_class` of `MINOR`, `MAJOR`, or `HAZARD` that selects the pricing row. Issuance takes the notice from `DRAFT` straight to `ISSUED` in the single call. Two preconditions guard it: the named `source_inspection_id` must point to an inspection on this same case whose outcome is `VIOLATION_FOUND`, failing which the issue is rejected with `ERR_NO_SUBSTANTIATION`; and a `FeeSchedule` row must exist for the notice's `violation_class`, failing which it is rejected with `ERR_FEE_SCHEDULE_MISSING`.

On issuance the system performs a tightly ordered set of side effects. It stamps `effective_date` with the current clock; this is the anchor from which both the cure window and any later accrual are measured. It copies the case's property owner onto the notice as `owner_id`, fixing the repeat-offender subject. It freezes the `escalation_multiplier` from that owner's live repeat tier (described in §3.5). It computes the `compliance_deadline` as the effective date plus the fee schedule's `cure_days` whole days — the last instant before overdue accrual can begin. It creates the citation ledger line (a `Fine` with `source_kind` of `CITATION` and `settlement_status` of `OPEN`) sized by the base of the accrual formula. Finally it recomputes the parent case's posture, advancing it from `INTAKE` to `ACTIVE`, recomputes `outstanding_balance_cents`, and increments the case's `version` by one. A notice read returns its live `fine_total_cents` and `days_overdue`, and a notice list can be filtered by `case_id`, `owner_id`, or `source_inspection_id`.

### 3.5. Repeat-Offender Escalation

The penalty an owner faces scales with their recent history. An owner's `prior_violation_count` is the number of that owner's violation notices, across all of the owner's properties, whose status is `COMPLIED` or `UPHELD` and whose `effective_date` falls within a rolling window — at or after the window start and at or before the current clock — where the window start is the current clock minus 365 days. When this count is evaluated for a notice being issued, the notice currently being issued is excluded from its own count. From that count the system selects a `repeat_tier`: the tier is `CHRONIC` when the prior count is at least four, otherwise `REPEAT` when the prior count is at least two, otherwise `FIRST`. The tier maps to a multiplier of exactly `1.0` for `FIRST`, `1.5` for `REPEAT`, and `2.0` for `CHRONIC`.

This score is evaluated in two distinct moments that must not be conflated. At issuance, the tier is computed once and its multiplier is frozen onto the notice as `escalation_multiplier`; that frozen value never changes for that notice afterward, no matter how the owner's history later shifts. On an owner read, by contrast, the tier is recomputed live against the current clock and reported as the owner's `repeat_tier` alongside the live `prior_violation_count`; this live tier may legitimately differ from the multiplier frozen onto any individual notice.

### 3.6. Overdue Accrual and the Provisional-versus-Settlement Fine

A notice's `fine_total_cents` is the money figure at the heart of the system, and it has two faces. While a notice is `OVERDUE`, the figure is provisional: it is recomputed on every read against the current clock and grows as days pass. Once a notice reaches `COMPLIED`, `UPHELD`, `DISMISSED`, or `SETTLED`, or once a contest pauses accrual, the figure is frozen at its settlement value as of the freezing instant and never changes again.

The accrual itself is computed as follows. The applicable fee schedule is the row for the notice's `violation_class`. The number of whole overdue days, `days_overdue`, is the whole days elapsed between the `compliance_deadline` and the as-of instant, computed by taking the difference of the two instants in seconds, dividing by 86,400, and taking the floor; if that result is negative it is treated as zero, so `days_overdue` never drops below zero. The raw accrual is the schedule's `base_fine_cents` plus its `daily_accrual_cents` multiplied by `days_overdue`. That raw figure is then capped at the schedule's `max_total_cents` by taking the smaller of the two. Only after the cap is applied does the escalation multiplier come in: the capped, pre-multiplier figure is multiplied by the notice's frozen `escalation_multiplier`, and that single product is rounded half-up to the nearest whole cent to yield `fine_total_cents`. The multiplier is applied after the cap, and the half-up rounding happens exactly once on the final product — the daily accrual is never rounded per-day.

The as-of instant is what distinguishes the two variants. In the provisional variant, while the notice is `OVERDUE`, the as-of instant is the current clock, so the total grows each day until it hits the cap. In the settlement variant — when the notice transitions to `COMPLIED`, `UPHELD`, `DISMISSED`, or `SETTLED`, or when a contest pauses accrual — the as-of instant is frozen to the transition instant (the re-inspection's `result_on`, the hearing decision instant, the payment instant, or the contest filing instant), and the value is fixed thereafter.

A notice crosses from `ISSUED` to `OVERDUE` automatically and lazily: the transition is evaluated on read or on any transition attempt, and it fires when the current clock has passed the `compliance_deadline` and no passing re-inspection has been recorded. Conversely, a notice that is cured within its window goes from `ISSUED` to `COMPLIED` when a re-inspection passes while the current clock is at or before the `compliance_deadline`, and at that point the citation fine settles to `SETTLED` if its assessed amount equals the base only, otherwise it remains `OPEN`.

### 3.7. Re-Inspection and Curing a Notice

To verify that a cited owner has fixed the problem, a `CodeOfficer` schedules a `Reinspection` naming the `notice_id` of the notice under review; the officer's opaque identifier is captured as `requested_by_user_id`. A new re-inspection has a `result` of `SCHEDULED` and a null `result_on`. When the officer records the result, `result_on` is stamped with the current clock and the supplied `result` of `PASSED` or `FAILED` is recorded. A `PASSED` result cures the notice and a `FAILED` result leaves it overdue. A notice's re-inspections can be listed as a sub-resource of the notice.

A passing re-inspection drives the notice's cure. From `ISSUED`, recording a passing re-inspection while the current clock is at or before the `compliance_deadline` moves the notice to `COMPLIED` and freezes its fine at the settlement variant with no overdue accrual. From `OVERDUE`, recording a passing re-inspection moves the notice to `COMPLIED` and freezes `fine_total_cents` at the settlement variant computed as of the re-inspection's `result_on` instant; the case's `outstanding_balance_cents` and posture are then recomputed.

### 3.8. Contesting a Notice and the Hearing Cycle

A cited owner may challenge a notice. Acting as a `Registrant`, the owner contests a notice by supplying the `scheduled_for` instant at which they want the hearing set. The acting registrant must own the case's property — their `X-User-ID` must equal the property's owner of record — or the contest is rejected with `ERR_NOT_NOTICE_OWNER`. The contest window depends on the notice's current state. From `ISSUED`, the contest must be filed while the current clock is at or before the `compliance_deadline`. From `OVERDUE`, the window is extended by a three-day grace period, so the contest must be filed while the current clock is at or before the `compliance_deadline` plus three days. A contest filed past the applicable window is rejected with `ERR_CONTEST_WINDOW_CLOSED`. In addition, the requested `scheduled_for` must respect the hearing buffer described below, or the contest is rejected with `ERR_HEARING_SLOT_CONFLICT`.

A valid contest pauses accrual — `fine_total_cents` is frozen at its provisional value as of the contest filing instant — and creates a `Hearing` in `SCHEDULED` status, recording the contesting registrant's `Owner.id` as `requested_by_user_id`. The hearing's `scheduled_for` must be at or after the contest filing instant. A new hearing has a `continuance_count` of zero. A notice's hearings can be listed as a sub-resource of the notice, and a hearing can be fetched directly.

A `HearingOfficer` runs the hearing. A hearing may be decided only once the current clock is at or after its `scheduled_for`; deciding early is rejected with `ERR_HEARING_NOT_RIPE`. The officer supplies a `decision` of `UPHELD` or `DISMISSED`. An `UPHELD` decision moves the hearing to `HELD_UPHELD` and drives the parent notice from `CONTESTED` to `UPHELD`. A `DISMISSED` decision moves the hearing to `HELD_DISMISSED` and drives the parent notice from `CONTESTED` to `DISMISSED`. Both `HELD_UPHELD` and `HELD_DISMISSED` are terminal for the hearing.

Alternatively the officer may continue a scheduled hearing, postponing it. Continuing moves the hearing to `CONTINUED` and increments `continuance_count` by one, but only while `continuance_count` is below the cap of two continuances; a third attempt is rejected with `ERR_CONTINUANCE_LIMIT`. From `CONTINUED`, the officer reschedules to put the hearing back to `SCHEDULED` with a new `scheduled_for`, which must be at or after the current clock or the reschedule is rejected with `ERR_HEARING_NOT_RIPE`. A reschedule target must also honor the hearing buffer.

The hearing buffer keeps two hearings on the same case from crowding each other. When a contest creates a hearing or a continued hearing is rescheduled, the chosen `scheduled_for` must be at least seven whole days away — in either direction — from the `scheduled_for` of any other hearing on the same case that is currently `SCHEDULED` or `CONTINUED`. Adjacency within seven whole days is forbidden; a violation is rejected with `ERR_HEARING_SLOT_CONFLICT`. This minimum-gap buffer between point-in-time hearings is deliberately stricter than the exclusive-occupancy overlap rule that governs cases.

### 3.9. The Effect of a Hearing Decision on Fines

When a hearing is upheld, the notice goes from `CONTESTED` to `UPHELD` and accrual resumes: the system recomputes `fine_total_cents` as the settlement variant bridging the paused contest interval, evaluated as of the decision instant, and sets the citation fine's `assessed_cents` to that frozen total while leaving the fine `OPEN`. The case's `outstanding_balance_cents` and posture are recomputed.

When a hearing is dismissed, the notice goes from `CONTESTED` to `DISMISSED`. This is a compensating outcome: the citation fine's `settlement_status` is set to `WAIVED`, which removes this notice's fine from the outstanding balance, and `fine_total_cents` is frozen to zero. The case's `outstanding_balance_cents` is recomputed with that debit removed, and the posture is recomputed.

### 3.10. The Fine Ledger and the Case Balance

Each `Fine` is one ledger line tied to a notice by `notice_id`. Its `source_kind` is `CITATION` for the penalty ledger or `ABATEMENT_COST` for recovered abatement expense. Its `assessed_cents` is the frozen amount at the point the line was finalized. Its `settlement_status` is `OPEN`, `SETTLED`, or `WAIVED`: an `OPEN` line accrues toward a lien, while `SETTLED` and `WAIVED` lines do not. A notice's fines can be listed as a sub-resource of the notice.

A case's `outstanding_balance_cents` is the sum of the provisional `fine_total_cents` over the case's violation notices that are not in `DISMISSED` or `SETTLED` status, plus any recorded abatement cost (the sum of `assessed_cents` over the case's `OPEN` `ABATEMENT_COST` fines), minus the `payments_applied_cents` posted against the case. The result is floored at zero — should accumulated payments exceed the open ledger (for instance because a lien payment also covers the administrative fee, which is not itself a `Fine` line), the balance is reported as zero rather than a negative number. This balance is recomputed on every relevant child mutation and previewed live on a case read.

A `FinanceClerk` posts a payment against a case by supplying an `amount_cents` and an `expected_case_version`. As with lien recording, the supplied `expected_case_version` must match the case's current `version`. The payment adds `amount_cents` to `payments_applied_cents`, then allocates the money to the case's `OPEN` citation and abatement-cost fines in order of each fine's creation timestamp ascending — oldest first; allocation proceeds fine by fine and stops at the first fine the remaining funds cannot fully cover, so partial coverage of a fine leaves it (and every later fine) `OPEN`. A notice is judged settled by its `OPEN` `CITATION` fines alone: a notice all of whose `OPEN` citation fines are fully covered by the allocation settles, where a `UPHELD` notice moves to `SETTLED` and an `OVERDUE` notice moves to `SETTLED` (freezing its `fine_total_cents` at the settlement variant as of the payment instant), and in both cases the covered citation fine's `settlement_status` becomes `SETTLED`. The payment recomputes the case's `outstanding_balance_cents` and posture and increments the case's `version` by one. Although it mutates the case rather than creating a stand-alone resource, this payment endpoint responds with `201 Created`.

### 3.11. Abatement: Board-Up and Demolition

When a property is dangerous, a `CodeOfficer` orders abatement against a `case_id`, choosing an `action_kind` of `BOARD_UP` or `DEMOLITION` and supplying an `estimated_cost_cents` contractor estimate. A new order is `ORDERED`, and placing it recomputes the case posture toward `ABATEMENT`. Demolition is tightly gated: ordering a `DEMOLITION` requires that the property's `occupancy` be `VACANT` and that the case carry a `HAZARD`-class notice in either `OVERDUE` or `UPHELD` status; otherwise the order is rejected with `ERR_DEMOLITION_NOT_PERMITTED`. A case's abatement orders can be listed as a sub-resource of the case, and an order can be fetched directly.

An ordered abatement is started by a code officer, moving it from `ORDERED` to `IN_PROGRESS`, which is permitted while the case posture is `ABATEMENT` or `ACTIVE`. From `IN_PROGRESS`, the officer completes the order, but only when the body supplies `actual_cost_cents` — completing without it is rejected with `ERR_MISSING_ACTUAL_COST`. On completion the order moves to `COMPLETED` and the system creates an abatement-cost ledger line: a `Fine` with `source_kind` of `ABATEMENT_COST`, `assessed_cents` equal to the supplied `actual_cost_cents`, and `settlement_status` of `OPEN`, attached to the case's most recent `UPHELD` or `OVERDUE` notice — "most recent" meaning the one with the latest creation order among those candidate notices. If the case carries no `UPHELD` or `OVERDUE` notice at completion, the order still moves to `COMPLETED` but no abatement-cost fine is created. The case's `outstanding_balance_cents` and posture are then recomputed with the abatement cost added. Alternatively, an order still in `ORDERED` (not yet started) may be cancelled by a code officer, moving it to `CANCELLED` and recomputing the case posture. Both `COMPLETED` and `CANCELLED` are terminal for an abatement order.

### 3.12. Recording, Releasing, and Foreclosing a Lien

When penalties go unpaid, a `FinanceClerk` records a `Lien` against the case to encumber the parcel. The request names the `case_id` and carries the mandatory `expected_case_version` for optimistic concurrency (§2.7). Beyond the stale-version guard, two further preconditions apply: the case's `outstanding_balance_cents` must be greater than zero, or the record is rejected with `ERR_NOTHING_TO_LIEN`; and there must be no existing lien for the case already in `PENDING` or `RECORDED` status, or it is rejected with `ERR_LIEN_ALREADY_EXISTS`. A lien begins life conceptually at `PENDING` and the successful recording lands it at `RECORDED`.

Recording freezes the money. First, every `OPEN` citation fine sitting on an `OVERDUE` or `UPHELD` notice is frozen: that fine's `assessed_cents` is set to its notice's settlement `fine_total_cents` as of the recording instant, and the fine stays `OPEN`. Then the lien amount is computed and frozen onto the lien. The `principal_cents` is the sum of `assessed_cents` over the case's `OPEN` citation fines plus the sum of `assessed_cents` over the case's `OPEN` abatement-cost fines; settled and waived lines are excluded. The administrative fee is keyed on the fully summed principal: the `admin_fee_cents` is the principal multiplied by an admin rate of `0.05` when the principal is below 500,000 cents, or `0.10` when the principal is at or above 500,000 cents, with that product rounded half-up to the nearest whole cent. The `total_cents` is the principal plus the administrative fee. The system copies the case's `property_id` onto the lien, recomputes the case posture to `LIENED`, and increments the case's `version` by one. (For a case read, the previewed outstanding balance uses the live provisional fine totals of overdue notices and carries no administrative fee; the administrative fee enters only at the moment of recording.)

A `RECORDED` lien is released by a finance clerk once it is paid in full — that is, once the case's `payments_applied_cents` is at least the lien's `total_cents`; an attempt to release with the lien not yet covered is rejected with `ERR_BALANCE_OUTSTANDING`. Releasing moves the lien to `RELEASED`, settles all remaining `OPEN` citation and abatement-cost fines on the case to `SETTLED`, and additionally moves every `OVERDUE` or `UPHELD` notice on the case to `SETTLED` so that no live fine total remains in the balance, then recomputes the case's `outstanding_balance_cents` to zero along with its posture. Alternatively, a `RECORDED` lien may be foreclosed by a finance clerk, but only once the current clock is at or after ninety days from the lien's `created_at`; foreclosing earlier is rejected with `ERR_FORECLOSURE_NOT_RIPE`. Foreclosing moves the lien to `FORECLOSED` and recomputes the case posture. Both `RELEASED` and `FORECLOSED` are terminal for a lien. Liens can be listed and filtered by `case_id` or by `property_id`, and a lien can be fetched directly.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and clock control — return `200 OK`. The complete request and response shapes for each endpoint are reconstructed from the workflow narratives in §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fee-schedules` | Create a fee schedule for a violation class | PlatformAdmin |
| GET | `/fee-schedules` | List fee schedules (filter by violation class) | PlatformAdmin, CodeOfficer, FinanceClerk |
| POST | `/_clock/set` | Set the server's logical UTC clock | PlatformAdmin |
| POST | `/owners` | Register a property owner | PlatformAdmin, CodeOfficer |
| GET | `/owners/{id}` | Get an owner with live repeat tier and prior count | PlatformAdmin, CodeOfficer, FinanceClerk, Registrant |
| POST | `/properties` | Create a property parcel | PlatformAdmin, CodeOfficer |
| GET | `/properties/{id}` | Get a property | PlatformAdmin, CodeOfficer, FinanceClerk, Registrant |
| GET | `/properties` | List properties (filter by owner) | PlatformAdmin, CodeOfficer, FinanceClerk |
| POST | `/cases` | Open an enforcement case on a property | CodeOfficer |
| GET | `/cases/{id}` | Get a case with live posture and balance | PlatformAdmin, CodeOfficer, FinanceClerk, Registrant |
| GET | `/cases` | List cases (filter by property) | PlatformAdmin, CodeOfficer, FinanceClerk |
| POST | `/cases/{id}/close` | Close a fully resolved case | FinanceClerk |
| POST | `/cases/{id}/payments` | Post a payment against the case | FinanceClerk |
| POST | `/complaints` | File a complaint under a case | CodeOfficer, Registrant |
| GET | `/cases/{id}/complaints` | List a case's complaints | PlatformAdmin, CodeOfficer, FinanceClerk |
| POST | `/complaints/{id}/triage` | Triage a received complaint | CodeOfficer |
| POST | `/complaints/{id}/dismiss` | Dismiss a received complaint | CodeOfficer |
| POST | `/inspections` | Schedule an initial or re-inspection inspection | CodeOfficer |
| GET | `/inspections/{id}` | Get an inspection | PlatformAdmin, CodeOfficer, FinanceClerk, Registrant |
| GET | `/inspections` | List inspections (filter by case or notice) | PlatformAdmin, CodeOfficer, FinanceClerk |
| POST | `/inspections/{id}/submit` | Submit an inspection outcome | CodeOfficer |
| POST | `/notices` | Issue a violation notice | CodeOfficer |
| GET | `/notices/{id}` | Get a notice with live fine and days overdue | PlatformAdmin, CodeOfficer, FinanceClerk, Registrant |
| GET | `/notices` | List notices (filter by case, owner, inspection) | PlatformAdmin, CodeOfficer, FinanceClerk, Registrant |
| POST | `/notices/{id}/contest` | Contest a notice, opening a hearing | Registrant |
| POST | `/reinspections` | Schedule a re-inspection of a notice | CodeOfficer |
| GET | `/notices/{id}/reinspections` | List a notice's re-inspections | PlatformAdmin, CodeOfficer, FinanceClerk, Registrant |
| POST | `/reinspections/{id}/result` | Record a re-inspection result | CodeOfficer |
| GET | `/notices/{id}/fines` | List a notice's fine ledger lines | PlatformAdmin, CodeOfficer, FinanceClerk, Registrant |
| GET | `/hearings/{id}` | Get a hearing | PlatformAdmin, CodeOfficer, FinanceClerk, HearingOfficer, Registrant |
| GET | `/notices/{id}/hearings` | List a notice's hearings | PlatformAdmin, CodeOfficer, FinanceClerk, HearingOfficer, Registrant |
| POST | `/hearings/{id}/decide` | Adjudicate a hearing upheld or dismissed | HearingOfficer |
| POST | `/hearings/{id}/continue` | Continue (postpone) a scheduled hearing | HearingOfficer |
| POST | `/hearings/{id}/reschedule` | Reschedule a continued hearing | HearingOfficer |
| POST | `/abatement-orders` | Order abatement (board-up or demolition) | CodeOfficer |
| GET | `/abatement-orders/{id}` | Get an abatement order | PlatformAdmin, CodeOfficer, FinanceClerk |
| GET | `/cases/{id}/abatement-orders` | List a case's abatement orders | PlatformAdmin, CodeOfficer, FinanceClerk |
| POST | `/abatement-orders/{id}/start` | Start an ordered abatement | CodeOfficer |
| POST | `/abatement-orders/{id}/complete` | Complete abatement and capture actual cost | CodeOfficer |
| POST | `/abatement-orders/{id}/cancel` | Cancel an ordered abatement | CodeOfficer |
| POST | `/liens` | Record a lien for the case's outstanding balance | FinanceClerk |
| GET | `/liens/{id}` | Get a lien | PlatformAdmin, CodeOfficer, FinanceClerk, Registrant |
| GET | `/liens` | List liens (filter by case or property) | PlatformAdmin, CodeOfficer, FinanceClerk, Registrant |
| POST | `/liens/{id}/release` | Release a recorded lien once paid in full | FinanceClerk |
| POST | `/liens/{id}/foreclose` | Foreclose a recorded lien after the waiting period | FinanceClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_NOTICE_OWNER` | 403 |
| `ERR_NO_SUBSTANTIATION` | 422 |
| `ERR_FEE_SCHEDULE_MISSING` | 422 |
| `ERR_DEMOLITION_NOT_PERMITTED` | 422 |
| `ERR_CONTEST_WINDOW_CLOSED` | 422 |
| `ERR_HEARING_NOT_RIPE` | 422 |
| `ERR_CONTINUANCE_LIMIT` | 422 |
| `ERR_FORECLOSURE_NOT_RIPE` | 422 |
| `ERR_LIEN_ALREADY_EXISTS` | 409 |
| `ERR_NOTHING_TO_LIEN` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BALANCE_OUTSTANDING` | 409 |
| `ERR_MISSING_ACTUAL_COST` | 422 |
| `ERR_DUPLICATE_PARCEL` | 409 |
| `ERR_REINSPECTION_TARGET_INVALID` | 422 |
| `ERR_PROPERTY_HAS_OPEN_CASE` | 409 |
| `ERR_HEARING_SLOT_CONFLICT` | 409 |
