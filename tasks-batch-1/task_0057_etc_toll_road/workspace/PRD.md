# ETC Toll Road API — Product Requirements Document

## 1. Introduction

This document specifies an electronic toll collection (ETC) platform in the style of regional interoperable systems such as E-ZPass. The platform models the full life of a toll charge: a motorist opens a prepaid account, registers vehicles, mounts transponders, and either drives through a gantry that reads the transponder or has a camera capture the license plate. Each gantry read becomes a priced charge that is debited from the account's prepaid balance, escalated into a fine when a plate-read toll goes unpaid, or exempted entirely when the vehicle declared a qualifying carpool window.

The system has to reconcile several concerns at once. Pricing is a two-variant calculation — transponder reads and camera (Toll-by-Plate) reads follow different surcharge rules, and multi-segment trips are billed as one charge with order-sensitive rounding. Money moves through an append-only ledger so that every balance change is auditable. A vehicle's transponder-binding history and its carpool declarations both feed into how a given read is priced, which makes the timing of bindings and windows materially affect the charge. Finally, the platform is interoperable: a partner agency in another state can post a toll read for one of our vehicles, and the home authority withholds a clearing fee before debiting the account. The requirements below define the entities, their state machines, the pricing and fine calculations, the validation order, and the role-based access rules that govern all of this.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the principal's operational capacity. If `X-User-Role` is missing or is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the header is present and recognized but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The platform recognizes exactly four roles: `AccountHolder`, `TollOperator`, `InteropClerk`, and `SystemAdmin`.

When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; this identity is entity-backed. Ownership checks on any resource that references an `Account` compare the resource's owning-account foreign key to `X-User-ID`. Concretely, a `Vehicle` and a `Transponder` reference their owner through `account_id`; a `TransponderBinding` is owned through its transponder's and vehicle's `account_id`; an `HovWindow` is owned through its vehicle's `account_id`; and a `Violation` is owned through its resolved `account_id`. When an `AccountHolder` acts on a resource owned by a different account, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

When `X-User-Role` is `TollOperator`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same holds for `InteropClerk` and `SystemAdmin`: each is an opaque identifier for, respectively, a partner-agency clearing clerk and the platform operator, neither of which is matched against a stored entity. A `TollOperator` runs plazas, pricing, settlement, the violation pipeline, and account lifecycle actions; an `InteropClerk` posts cross-state toll reads carrying an `interop_agency_id`; a `SystemAdmin` registers partner agencies and manages registration state.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped before collection begins; it defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in this system — `Account`, `Vehicle`, `Transponder`, `TransponderBinding`, `HovWindow`, `Plaza`, `TollTransaction`, `Violation`, and `InteropAgency` — carry a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits set at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that begins at 1 and increments by 1 on every mutation of the resource.

The `LedgerEntry` resource is the sole exception. A ledger entry is an append-only event and is never modified after it is written, so it carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field.

Any server-initiated reconciliation — a cascade that flips a dependent resource's state, a recomputation of a derived field — is itself a mutation: it refreshes `updated_at` and increments `version` on each resource it touches, exactly as a client-initiated change would.

### 2.5. Monetary Values and Precision

Every monetary quantity in the system is stored and exchanged as an integer number of cents — balances, thresholds, rates, tolls, penalties, and fines are all integer-cents fields, never decimal dollars. Surcharge and fee rates are expressed in basis points, where 10000 basis points equal a full multiplier of one (so 2500 basis points denotes a 25% surcharge).

Wherever a calculation multiplies by a basis-point rate, the result is rounded to a whole number of cents using the round-half-up method (a value exactly halfway between two integers rounds up to the larger magnitude). When a single calculation applies more than one multiplicative step — for instance a peak multiplier followed by a plate surcharge — each multiplicative step is rounded to whole cents in turn, in the stated order, rather than being deferred to a single rounding at the end. Calculations described as exact (penalties, fine totals, aggregations, fixed top-ups) involve only integer addition and subtraction and need no rounding.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. Each guarded write requires the client to submit the version of the parent resource it last observed; if that version no longer matches the parent's current `version`, the write is refused with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated.

Binding a transponder to a vehicle requires the field `expected_vehicle_version`, carrying the client's last observed `version` of the target `Vehicle`. If another writer has advanced that vehicle's `version` since the client read it — for example by creating a competing binding, since a vehicle's binding history governs which transponder prices its tolls — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from writing a binding against a vehicle snapshot it has not actually seen.

Repricing a toll transaction requires the field `expected_transaction_version`, carrying the client's last observed `version` of the target `TollTransaction`. The transaction's `version` is bumped by any settlement transition or cascade applied after the client's read; a reprice carrying the prior version is therefore operating on a stale snapshot and is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field. Endpoints not named above perform no version check.

### 2.7. Referential Integrity and Resolution Order

Every foreign-key identifier supplied in a path or request body must resolve to an existing resource. Identifiers are validated left to right in the order they appear, and the first one that does not resolve causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404). This ordering applies uniformly: existence is established before any state, ownership, or business rule is evaluated.

### 2.8. The Append-Only Ledger

Every movement of money against an account is recorded as a `LedgerEntry`. A ledger entry names the `account_id` whose balance moved, an `entry_type`, a signed `amount_cents` (negative for debits, positive for credits), the resulting `balance_after_cents` (the account's `balance_cents` immediately after the entry was applied), and, where applicable, a `ref_transaction_id` pointing at the originating toll transaction and/or a `ref_violation_id` pointing at the originating violation. The `entry_type` is one of `TOLL_DEBIT`, `RELOAD_CREDIT`, `VIOLATION_SETTLE`, `DISPUTE_REFUND`, or `INTEROP_DEBIT`. The ledger is the durable audit trail for the account; entries are written as their triggering events occur and are never altered afterward.

### 2.9. Validation Priority Order

When an endpoint could fail more than one check, the checks are evaluated in a fixed priority order, and the first failing check determines the error returned. The order is: (1) authentication — `X-User-Role` is present and a known role, else `ERR_UNAUTHENTICATED` (401); (2) role authorization — the role is permitted for this operation per the access rules, else `ERR_FORBIDDEN_ROLE` (403); (3) existence — every path and body foreign-key id resolves, validated left to right, else `ERR_NOT_FOUND` (404); (4) resource ownership — for `AccountHolder` operations, `X-User-ID` must own the targeted account, vehicle, or transponder, else `ERR_NOT_RESOURCE_OWNER` (403); (5) state validity — the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE` (409); (6) through (16) the domain-specific business rules described throughout §3, in the order listed below; (17) the optimistic-concurrency version check, else `ERR_STALE_VERSION` (412); and (18) the structural body check — valid JSON, required fields present, enum values legal, numeric constraints satisfied, else `ERR_VALIDATION` (422).

The business-rule band (priorities 6 through 16), evaluated in this relative order after state validity and before the concurrency and structural checks, is: binding ownership match (`ERR_OWNERSHIP_MISMATCH`), owning-account-active on bind (`ERR_ACCOUNT_NOT_ACTIVE`), plate-registration eligibility (`ERR_PLATE_UNREGISTERED`), binding-interval overlap (`ERR_BINDING_OVERLAP`), HOV-window buffered overlap (`ERR_HOV_WINDOW_OVERLAP`), occupancy floor (`ERR_INVALID_OCCUPANCY`), serial uniqueness (`ERR_DUPLICATE_SERIAL`), violation eligibility (`ERR_NOT_VIOLATION_ELIGIBLE`), interop-agency-active (`ERR_INTEROP_AGENCY_INACTIVE`), sufficient balance to pay a fine (`ERR_INSUFFICIENT_BALANCE`), and zero-balance-to-close (`ERR_BALANCE_NONZERO`). Each of these is detailed alongside the workflow it guards in §3.

## 3. Business Logic & Workflows

### 3.1. Accounts, Balances, and Auto-Reload

An account is opened by supplying a `holder_name` and a two-letter `home_state_code`. A new account begins in `ACTIVE` status with a `balance_cents` of 0. The balance is a prepaid pool that tolls draw down; it is allowed to go negative when a toll posts against insufficient funds. Account `status` is one of `ACTIVE`, `DELINQUENT`, `SUSPENDED`, or `CLOSED`.

At creation the holder may configure auto-reload. The `low_balance_threshold_cents` is the balance at or below which auto-reload fires; it must be at least 0 and defaults to 1000. The `auto_reload_enabled` flag arms the feature and defaults to false. The `reload_policy` chooses between two top-up algorithms and is either `FIXED` or `RESTORE_TO_TARGET`, defaulting to `FIXED`. Under the `FIXED` policy the system adds a flat `reload_amount_cents` (which must be greater than 0 when auto-reload is enabled, and defaults to 4000) regardless of the current balance. Under the `RESTORE_TO_TARGET` policy the system tops up just enough to bring the balance up to `target_balance_cents`; when this policy is selected, `target_balance_cents` must be greater than `low_balance_threshold_cents`, and it defaults to 5000.

Auto-reload is evaluated immediately after any ledger entry that decreases the balance — a toll debit, an interop debit, or a violation settlement. If `auto_reload_enabled` is true and the resulting `balance_cents` is at or below `low_balance_threshold_cents` (the boundary is inclusive — equal counts), a reload fires. Under `FIXED`, the credited amount is exactly `reload_amount_cents`. Under `RESTORE_TO_TARGET`, the credited amount is the difference between `target_balance_cents` and the current (possibly negative) balance, but never less than zero — if the current balance already meets or exceeds the target, nothing is credited. Each reload appends a `LedgerEntry` of type `RELOAD_CREDIT`.

Separately from auto-reload, the holder or an operator may make a manual one-off deposit. A credit operation supplies an `amount_cents`, adds it to `balance_cents`, and appends a `RELOAD_CREDIT` ledger entry recording the new balance.

A read-only `outstanding_fines_cents` on the account is the sum of `fine_total_cents` over every `Violation` of that account whose settlement status is `ASSESSED` or `CONTESTED`; violations that are `SETTLED` or `DISMISSED` are excluded. It begins at 0 and is recomputed whenever a violation of the account is created, paid, accepted, or rejected.

### 3.2. Account Lifecycle Transitions

The account state machine begins at `ACTIVE` and terminates at `CLOSED`. Several transitions are driven by the system and several by a `TollOperator`.

The system moves an `ACTIVE` account to `DELINQUENT` when a violation for that account reaches `ASSESSED`; this recomputes `outstanding_fines_cents`. The reverse is also system-driven: when every violation of a `DELINQUENT` account has left the `ASSESSED` and `CONTESTED` set — equivalently, when `outstanding_fines_cents` falls to 0 — the account returns from `DELINQUENT` to `ACTIVE`.

An operator may suspend an account. Suspension is permitted from either `ACTIVE` or `DELINQUENT`, and in both cases moves the account to `SUSPENDED`. Suspension carries a cascade: every `BOUND` transponder of the account is moved to `DEACTIVATED`, and each of those transponders' `ACTIVE` bindings is moved to `ENDED` with `effective_to` set to the moment of suspension. A suspend request may carry an optional `reason`.

An operator may reinstate a `SUSPENDED` account, moving it back to `ACTIVE`; reinstatement is only allowed when `outstanding_fines_cents` is 0. An operator may close an account only from `SUSPENDED`, and only when both `balance_cents` is exactly 0 and `outstanding_fines_cents` is exactly 0; a close attempt that violates either condition is rejected with `ERR_BALANCE_NONZERO` (HTTP 409). Closing moves the account to the terminal `CLOSED` state. Any state transition requested against an account that is not in the required source state is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. Vehicles and Transponders

A vehicle is registered under an account by supplying its `account_id`, a `plate_number` (stored uppercased), and a two-letter `plate_state_code`; optionally a `hov_capable` flag (defaulting to false) marking whether the vehicle may declare carpool windows, and an `axle_count` (which must be at least 2, defaulting to 2) feeding axle-tier pricing. A new vehicle's `registration_status` is `REGISTERED`. The only other value is `LAPSED`; an operator or administrator may force a vehicle to `LAPSED` via the lapse-registration capability. A `LAPSED` plate cannot be priced at the transponder rate — see §3.6.

A transponder is created under an account by supplying its `account_id` and a hardware `serial`. The serial must be unique across all transponders in the system; a duplicate is rejected with `ERR_DUPLICATE_SERIAL` (HTTP 409). A transponder's `status` starts at `UNBOUND` and may move to `BOUND` or to the terminal `DEACTIVATED`.

A transponder is deactivated by the system as a side effect of its owning account being suspended: a `BOUND` transponder moves to `DEACTIVATED` and its `ACTIVE` binding is ended, while an `UNBOUND` transponder simply moves to `DEACTIVATED` with no binding to end.

### 3.4. Binding a Transponder to a Vehicle

An `AccountHolder` mounts a transponder on one of their vehicles by creating a binding. The request supplies the `transponder_id`, the `vehicle_id`, an `effective_from` instant (inclusive), an optional `effective_to` instant (exclusive; left null while the binding is open), and the concurrency field `expected_vehicle_version` described in §2.6. A successful bind creates a `TransponderBinding` row in `ACTIVE` status, moves the transponder from `UNBOUND` to `BOUND`, and increments the vehicle's `version` by 1.

Several conditions guard the bind, evaluated in the priority order of §2.9. The transponder must currently be `UNBOUND`; otherwise the state check fails with `ERR_INVALID_STATE` (409). The vehicle and the transponder must belong to the same account — that is, their `account_id` values must match — otherwise the bind is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 409). The owning account must be `ACTIVE`; binding under a `DELINQUENT`, `SUSPENDED`, or `CLOSED` account is rejected with `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409). The proposed binding interval, the half-open span from `effective_from` up to but not including `effective_to`, must not overlap any `ACTIVE` binding interval already on the same vehicle; because the intervals are half-open, two bindings that merely touch at a shared endpoint (one's `effective_to` equal to the next's `effective_from`) are allowed, but any true overlap is rejected with `ERR_BINDING_OVERLAP` (HTTP 409). Finally the concurrency check against `expected_vehicle_version` applies.

A binding's `status` is `ACTIVE` or `ENDED`. The holder may end an `ACTIVE` binding; ending it moves the binding to `ENDED` with `effective_to` set to the current moment and returns the transponder from `BOUND` to `UNBOUND`. Ending is only valid while the transponder is `BOUND`.

### 3.5. Carpool (HOV) Windows

A `hov_capable` vehicle may declare a carpool occupancy window so that qualifying trips during that span are exempt from tolls. Declaring a window supplies the `vehicle_id`, a `window_from` instant (inclusive), a `window_to` instant (exclusive), and `declared_occupants`, the number of people in the vehicle, which must be at least 1; a value below 1 is rejected with `ERR_INVALID_OCCUPANCY` (HTTP 422). A window's `status` is `DECLARED` on creation, and the holder may later revoke it, moving it to `REVOKED`.

Windows on the same vehicle are kept apart by a buffered, half-open interval rule. A new window's span, from `window_from` up to but not including `window_to`, must not overlap any existing `DECLARED` window on the same vehicle, and must not even abut one within a 15-minute buffer: if the gap between the new window and any existing declared window on that vehicle is less than 15 minutes, the declaration is rejected with `ERR_HOV_WINDOW_OVERLAP` (HTTP 409). Whether a given window actually exempts a particular toll additionally depends on the plaza's occupancy minimum, evaluated at pricing time as described in §3.6.

### 3.6. Plazas, Gantry Reads, and Pricing

A `TollOperator` configures a plaza with a `name`, a two-letter `state_code`, and its rate parameters. The `base_rate_cents` is the base off-peak toll for a 2-axle vehicle and must be greater than 0. The `peak_multiplier_bps` is the peak surcharge in basis points applied during peak hours (it must be at least 0 and defaults to 0). The `axle_surcharge_cents` is the per-axle surcharge charged for each axle beyond 2 (at least 0, default 0). The `hov_min_occupants` is the minimum declared occupancy required for a full HOV exemption at this plaza (at least 2, default 3). The `plate_surcharge_bps` is the Toll-by-Plate surcharge in basis points layered over the transponder toll (at least 0, default 5000).

A gantry read is recorded as a toll transaction. The recording request supplies the `plaza_id`, a `read_method` of either `TRANSPONDER` or `PLATE`, the `read_at` timestamp, an `is_peak` flag stating whether the read fell in a peak window, an optional `declared_axles` (axles sensed at the gantry, at least 2, default 2), and the read-method-specific fields: a `transponder_id` for transponder reads, or a captured `plate_number` and `plate_state_code` for plate reads. A partner-posted interop read additionally carries an `interop_agency_id`. On recording, the system resolves the owner: it sets `account_id` and `vehicle_id` (both system-managed and left null when resolution fails — a transponder that is not bound, or a captured plate that matches no vehicle). A new transaction is created with `pricing_status` of `PENDING` and `settlement_status` of `UNSETTLED`.

A toll transaction carries two independent status dimensions that evolve separately on the same row. The pricing dimension, `pricing_status`, is one of `PENDING`, `PRICED`, `EXEMPT`, or `REPRICED`. The settlement dimension, `settlement_status`, is one of `UNSETTLED`, `SETTLED`, `IN_VIOLATION`, or `WRITTEN_OFF`.

Pricing a `PENDING` transaction is a `TollOperator` action. It first requires that `account_id` is resolved; pricing a transaction whose account and vehicle could not be resolved is rejected with `ERR_UNRESOLVED_READ` (HTTP 409). The outcome then forks on whether a carpool exemption applies. If a `DECLARED` `HovWindow` on the resolved vehicle covers `read_at` and its `declared_occupants` is greater than or equal to the plaza's `hov_min_occupants`, the transaction goes to `EXEMPT`: `hov_exempt` is set to true, `gross_toll_cents` is still computed, `toll_cents` is set to 0, no account debit occurs, and the settlement dimension moves from `UNSETTLED` to `SETTLED` because nothing is owed. Otherwise — when no qualifying `DECLARED` window meeting the plaza's occupancy minimum covers `read_at` — the transaction goes to `PRICED` and is priced as below.

When priced under the transponder path, an additional eligibility rule applies to plate reads: a `PLATE`-read transaction may price at the transponder rate only if its matched vehicle's `registration_status` is `REGISTERED`. A `LAPSED` vehicle cannot price at transponder rate and is rejected with `ERR_PLATE_UNREGISTERED` (HTTP 409), forcing the plate-rate / violation path.

The gross toll is computed combinatorially. First, the axle surcharge is the number of axles above 2 — that is `declared_axles` minus 2, but never less than 0 — multiplied by the plaza's `axle_surcharge_cents`. Add this to the `base_rate_cents` to get the pre-peak amount. If `is_peak` is true, multiply the pre-peak amount by the peak factor — 10000 plus the plaza's `peak_multiplier_bps`, divided by 10000 — and round half up to whole cents; if `is_peak` is false, the pre-peak amount is used unchanged. The result is `gross_toll_cents`.

The final `toll_cents` then branches on read method. For an HOV-exempt read, `toll_cents` is 0 (handled by the `EXEMPT` branch above). For a transponder read, `toll_cents` equals `gross_toll_cents` with no further surcharge. For a plate read, the Toll-by-Plate surcharge applies: multiply `gross_toll_cents` by the plate factor — 10000 plus the plaza's `plate_surcharge_bps`, divided by 10000 — and round half up to whole cents. The two multiplicative steps round independently and in order: the peak step first, then the plate-surcharge step.

The debit behavior on pricing depends on the read method. For a transponder read, the account's `balance_cents` is debited by `toll_cents`, a `TOLL_DEBIT` ledger entry for the negative `toll_cents` is appended, and the settlement dimension moves from `UNSETTLED` to `SETTLED`. For a plate read that carries an `interop_agency_id`, the home authority withholds a clearing fee before debiting: the withheld amount is `toll_cents` multiplied by the agency's `settlement_fee_bps`, divided by 10000, rounded half up; the home debit is `toll_cents` minus that withheld amount; the account is debited by the home-debit amount, an `INTEROP_DEBIT` ledger entry for the negative home-debit amount is appended, and the settlement dimension moves to `SETTLED`. For a plate read with no `interop_agency_id`, no debit occurs and the settlement dimension stays `UNSETTLED`, awaiting either a manual settle or escalation into a violation. After any debit above, the auto-reload evaluation of §3.1 runs against the new balance.

### 3.7. Repricing, Manual Settlement, and Multi-Segment Trips

A `PRICED` transaction may be repriced by a `TollOperator`, provided its settlement dimension is not `WRITTEN_OFF`. The reprice request supplies a new `declared_axles`, a new `is_peak`, and the concurrency field `expected_transaction_version` (see §2.6). Repricing recomputes `toll_cents` via the same pricing formula, adjusts `balance_cents` by the difference between the new and the old `toll_cents`, appends a `TOLL_DEBIT` ledger entry for that delta, moves `pricing_status` from `PRICED` to `REPRICED`, and increments the transaction's `version` by 1.

Manual settlement is available for an `UNSETTLED` transaction whose pricing dimension is `PRICED`, `EXEMPT`, or `REPRICED`. Settling debits the account for any unpaid remainder, appends a `TOLL_DEBIT` ledger entry, runs the auto-reload evaluation, and moves the settlement dimension from `UNSETTLED` to `SETTLED`. (The system itself also performs this `UNSETTLED → SETTLED` move when a price or reprice is fully covered by funds.)

A multi-segment trip records and prices several plaza segments as one billed charge. The request supplies an `account_id` and an ordered list of `segments`, processed in request order. Each segment is priced independently through the per-read pricing formula of §3.6, producing an already-rounded whole-cent segment toll. The trip total is then the plain sum of those per-segment tolls — the order is pinned to round-per-segment-then-sum: each segment is rounded to whole cents first, and the already-rounded segment tolls are added together, with no second rounding applied to the sum. The trip creates one `TollTransaction` per segment, all in `PRICED` status, and debits the account by the trip total.

### 3.8. Escalation into Violations and the Dispute Cycle

When a Toll-by-Plate read goes unpaid, an operator may escalate it into a violation. A violation may be opened only on a transaction that is `PRICED`, still `UNSETTLED`, and was a `PLATE` read; an attempt against any transaction not meeting all three conditions is rejected with `ERR_NOT_VIOLATION_ELIGIBLE` (HTTP 409). Opening a violation supplies the `toll_transaction_id`. It creates a `Violation` in `ASSESSED` status, carries the underlying toll into `toll_due_cents` (taken from the transaction's `toll_cents` at issuance), records the resolved `account_id`, moves the linked transaction's settlement dimension from `UNSETTLED` to `IN_VIOLATION`, and — as a cascade — moves the owning account from `ACTIVE` to `DELINQUENT` if it was `ACTIVE`.

A violation's `settlement_status` is one of `ASSESSED`, `CONTESTED`, `SETTLED`, or `DISMISSED`, and the cycle between `ASSESSED` and `CONTESTED` may repeat. The fine is tiered by an `escalation_tier` that starts at 1. The penalty is a flat base administrative penalty of 2500 cents plus 1500 cents for each re-issue cycle beyond the first — that is, 2500 plus 1500 multiplied by the quantity (`escalation_tier` minus 1). The `fine_total_cents` is `toll_due_cents` plus `penalty_cents`. Both `penalty_cents` and `fine_total_cents` are computed at issuance and recomputed on each re-issue.

The `AccountHolder` may contest an `ASSESSED` violation, supplying a free-text `dispute_reason`; this stores the reason and moves the violation from `ASSESSED` to `CONTESTED`. A `TollOperator` adjudicates a `CONTESTED` violation in one of two ways. Rejecting the dispute moves it from `CONTESTED` back to `ASSESSED`, increments `escalation_tier` by 1, recomputes `penalty_cents` and `fine_total_cents` at the new tier, and recomputes the account's `outstanding_fines_cents`. Accepting the dispute moves it from `CONTESTED` to the terminal `DISMISSED`; as cascades, the linked transaction moves from `IN_VIOLATION` to `WRITTEN_OFF`, the account's `outstanding_fines_cents` is recomputed, and if that total is now 0 and the account is `DELINQUENT`, the account returns to `ACTIVE`.

The holder may pay a violation that is either `ASSESSED` or `CONTESTED`, provided the account's `balance_cents` is greater than or equal to `fine_total_cents`; an underfunded payment is rejected with `ERR_INSUFFICIENT_BALANCE` (HTTP 402). Payment debits `balance_cents` by `fine_total_cents`, appends a `VIOLATION_SETTLE` ledger entry, moves the violation to the terminal `SETTLED`, and cascades: the linked transaction moves from `IN_VIOLATION` to `SETTLED`, `outstanding_fines_cents` is recomputed, and if it is now 0 and the account is `DELINQUENT`, the account returns to `ACTIVE`. A transaction whose linked violation settles thus follows `IN_VIOLATION → SETTLED`, while one whose linked violation is dismissed follows `IN_VIOLATION → WRITTEN_OFF`.

### 3.9. Cross-State Interoperability

A `SystemAdmin` registers a partner tolling authority by supplying its `name`, two-letter `state_code`, an optional `settlement_fee_bps` (the interop clearing fee in basis points withheld from the home authority's share, at least 0, default 200), and an optional `active` flag (default true). An `InteropClerk` posts a cross-state toll read for one of our vehicles by recording a toll transaction that carries an `interop_agency_id`. Interop posting is only accepted when the referenced agency's `active` flag is true; a posting against an inactive agency is rejected with `ERR_INTEROP_AGENCY_INACTIVE` (HTTP 409). The home-share fee withholding that applies when such an interop plate read is priced is described in §3.6.

### 3.10. Ledger Retrieval

The ledger is queryable for audit. Ledger entries can be listed for a specific account, and can also be listed across the system filtered by the originating account (`account_id`), the originating toll transaction (`ref_transaction_id`), or the originating violation (`ref_violation_id`); a single entry is retrievable by its id. These reads expose the `entry_type`, signed `amount_cents`, `balance_after_cents`, and the originating references for each movement.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or read data return `200 OK`. Request and response bodies are not enumerated in this table — the fields each operation consumes and the effects it produces are described in the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/etc/accounts` | Create a toll account | AccountHolder, TollOperator |
| GET | `/etc/accounts/{id}` | Get an account | AccountHolder, TollOperator, SystemAdmin |
| POST | `/etc/accounts/{id}/credit` | Manually credit balance | AccountHolder, TollOperator |
| POST | `/etc/accounts/{id}/suspend` | Suspend an account | TollOperator |
| POST | `/etc/accounts/{id}/reinstate` | Reinstate a suspended account | TollOperator |
| POST | `/etc/accounts/{id}/close` | Close an account | TollOperator |
| GET | `/etc/accounts/{id}/ledger-entries` | List ledger entries for an account | AccountHolder, TollOperator, SystemAdmin |
| GET | `/etc/ledger-entries/{id}` | Get a single ledger entry | AccountHolder, TollOperator, SystemAdmin |
| GET | `/etc/ledger-entries` | List ledger entries, filterable by account, transaction, or violation | AccountHolder, TollOperator, SystemAdmin |
| POST | `/etc/vehicles` | Register a vehicle under an account | AccountHolder, TollOperator |
| GET | `/etc/vehicles/{id}` | Get a vehicle | AccountHolder, TollOperator, SystemAdmin |
| GET | `/etc/vehicles` | List vehicles, filterable by account | AccountHolder, TollOperator, SystemAdmin |
| POST | `/etc/vehicles/{id}/lapse-registration` | Mark a vehicle's registration LAPSED | TollOperator, SystemAdmin |
| POST | `/etc/transponders` | Create an UNBOUND transponder | AccountHolder, TollOperator |
| GET | `/etc/transponders/{id}` | Get a transponder | AccountHolder, TollOperator, SystemAdmin |
| GET | `/etc/transponders` | List transponders, filterable by account | AccountHolder, TollOperator, SystemAdmin |
| POST | `/etc/transponder-bindings` | Bind a transponder to a vehicle | AccountHolder |
| GET | `/etc/transponder-bindings/{id}` | Get a binding | AccountHolder, TollOperator, SystemAdmin |
| GET | `/etc/transponder-bindings` | List bindings, filterable by transponder or vehicle | AccountHolder, TollOperator, SystemAdmin |
| POST | `/etc/transponder-bindings/{id}/end` | End an active binding | AccountHolder |
| POST | `/etc/hov-windows` | Declare a carpool/HOV window | AccountHolder |
| GET | `/etc/hov-windows/{id}` | Get an HOV window | AccountHolder, TollOperator, SystemAdmin |
| GET | `/etc/hov-windows` | List HOV windows, filterable by vehicle | AccountHolder, TollOperator, SystemAdmin |
| POST | `/etc/hov-windows/{id}/revoke` | Revoke a declared HOV window | AccountHolder |
| POST | `/etc/plazas` | Create a toll plaza | TollOperator |
| GET | `/etc/plazas/{id}` | Get a plaza | AccountHolder, TollOperator, SystemAdmin |
| GET | `/etc/plazas/{id}/toll-transactions` | List toll transactions at a plaza | TollOperator, SystemAdmin |
| POST | `/etc/toll-transactions` | Record a gantry read | TollOperator, InteropClerk |
| GET | `/etc/toll-transactions/{id}` | Get a toll transaction | AccountHolder, TollOperator, InteropClerk, SystemAdmin |
| GET | `/etc/toll-transactions` | List toll transactions, filterable by account, vehicle, transponder, or interop agency | AccountHolder, TollOperator, InteropClerk, SystemAdmin |
| POST | `/etc/toll-transactions/{id}/price` | Price a pending transaction | TollOperator |
| POST | `/etc/toll-transactions/{id}/reprice` | Reprice a priced transaction | TollOperator |
| POST | `/etc/toll-transactions/{id}/settle` | Manually settle an unsettled priced transaction | TollOperator, AccountHolder |
| POST | `/etc/toll-transactions/batch-trip` | Record and price a multi-segment trip | TollOperator |
| POST | `/etc/violations` | Open a violation on an unpaid plate-read toll | TollOperator |
| GET | `/etc/violations/{id}` | Get a violation | AccountHolder, TollOperator, SystemAdmin |
| GET | `/etc/violations` | List violations, filterable by account or toll transaction | AccountHolder, TollOperator, SystemAdmin |
| POST | `/etc/violations/{id}/contest` | Contest a violation | AccountHolder |
| POST | `/etc/violations/{id}/accept-dispute` | Accept the dispute (dismiss) | TollOperator |
| POST | `/etc/violations/{id}/reject-dispute` | Reject the dispute (re-issue at higher tier) | TollOperator |
| POST | `/etc/violations/{id}/pay` | Pay a violation fine from account balance | AccountHolder |
| POST | `/etc/interop-agencies` | Register a cross-state partner agency | SystemAdmin |
| GET | `/etc/interop-agencies/{id}` | Get a partner agency | TollOperator, InteropClerk, SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_OWNERSHIP_MISMATCH` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_PLATE_UNREGISTERED` | 409 |
| `ERR_BINDING_OVERLAP` | 409 |
| `ERR_HOV_WINDOW_OVERLAP` | 409 |
| `ERR_INVALID_OCCUPANCY` | 422 |
| `ERR_DUPLICATE_SERIAL` | 409 |
| `ERR_NOT_VIOLATION_ELIGIBLE` | 409 |
| `ERR_INTEROP_AGENCY_INACTIVE` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 402 |
| `ERR_BALANCE_NONZERO` | 409 |
| `ERR_UNRESOLVED_READ` | 409 |
| `ERR_STALE_VERSION` | 412 |
