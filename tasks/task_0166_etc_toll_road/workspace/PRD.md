# ETC Toll Road API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Electronic Toll Collection (ETC) Toll Road API, the back-office system that underpins an E-ZPass-style tolling network spanning multiple state agencies. The API must reconcile two parallel realities at every gantry pass: a hardware reality, where a transponder may or may not be read, and a visual reality, where a license-plate camera attempts to identify the vehicle when the transponder is silent. From this raw signal the system attributes each event to an account, prices it under tiered class and cross-state interoperability rules, debits a prepaid balance, and — when attribution succeeds but funds are short, when the gantry recognizes neither transponder nor plate, or when an HOV claim cannot be substantiated — escalates the event into a civil violation that compounds if left unpaid.

Several intertwined business concerns drive the complexity of this surface. Account holders pay tolls through a stored balance that must auto-replenish under operator-controlled thresholds; agencies in different states share infrastructure but levy surcharges and discounts against one another's customers; high-occupancy-vehicle lanes provide exemptions that depend on declared occupancy and vehicle eligibility; and unpaid fines must cascade into vehicle and account suspensions while still permitting dispute, void, and rehabilitation paths. The contract documented below is the single source of truth for how these flows interact, including the precise ordering of pricing components, the exact conditions under which a passage is voided versus violated, and the lifecycle transitions that bind an account holder's billing relationship to enforcement.

## 2. Global Specifications & System-Wide Principles

This section describes cross-cutting rules that apply uniformly across every endpoint. Sections 2.1 through 2.3 are precise structural contracts; 2.4 through 2.10 define domain-wide policies whose specifics surface again, in context, throughout the business workflows in §3.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, which identifies the calling principal, and `X-User-Role`, which declares the operational capacity under which the request is made. The system recognizes exactly three roles spelled as follows: `AccountHolder`, `AgencyAdmin`, and `GantryOperator`. A request missing either header is rejected with `ERR_MISSING_AUTH`. A request whose `X-User-Role` value is not one of these three exact strings is rejected with `ERR_INVALID_ROLE`. A request whose role is valid but not authorized for the endpoint in question (see §4) is rejected with `ERR_FORBIDDEN`.

When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's `account_id` field (directly, or through its parent `Violation` in the case of a `Fine`) to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `AgencyAdmin` or `GantryOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`; an `AgencyAdmin` may act on behalf of any account.

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

Endpoints returning lists are paginated through two query parameters. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0 and represents the number of items to skip. Unless otherwise specified, list endpoints sort by `created_at` in ascending order. The pagination block surfaced in `meta` for list responses contains `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — `Account`, `Vehicle`, `Transponder`, `Violation`, `Fine` — carries a server-minted `id` formatted as a UUID with no type prefix, a `created_at` ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first persisted, an `updated_at` timestamp of the same shape that is refreshed on any mutation, and an integer `version` that starts at 1 and increments by 1 on every mutation. Two entities are deliberately treated as immutable event records and therefore carry only `id` and `created_at` (no `updated_at`, no `version`): the `TollEvent`, which represents a single gantry capture, and the `ReloadEvent`, which represents a single credit posted against an account's balance. The `InteropPolicy` row is likewise an event-style record that carries `id` and `created_at` only.

### 2.5. Path Resolution and Nested Resource Validation

When an endpoint path contains multiple resource identifiers (for example `/accounts/{account_id}/transponders/{transponder_id}/bind`), the server resolves identifiers strictly left-to-right. If `account_id` cannot be located the request is rejected with `ERR_NOT_FOUND` before `transponder_id` is consulted; only after the account is confirmed does the server look up the transponder. This ordering also applies to fines and toll events: when a path implies an ownership chain, the chain is walked outermost-first and the first missing element produces `ERR_NOT_FOUND`.

### 2.6. Monetary Precision and Per-Step Rounding

All monetary amounts in the system are stored and exchanged as integer cents — `base_rate_cents`, `gross_toll_cents`, `net_toll_cents`, `balance_cents`, `amount_cents`, `civil_penalty_cents`, `auto_reload_threshold_cents`, `auto_reload_topup_cents`, and `outstanding_fine_cents` are all whole integers. Whenever a pricing rule produces a fractional value the result is rounded half up to the nearest cent. Toll pricing is sensitive to where the rounding boundary falls: the class adjustment, the cross-state interoperability adjustment, and the plate-bill surcharge are each rounded half up to whole cents **at each individual step** before being combined; the rounding does not occur only at the end. The final value is then evaluated under the HOV exemption check.

### 2.7. Optimistic Concurrency Control

Mutating operations on an `Account` may carry the resource's current integer `version` in the request body to opt in to optimistic concurrency control. When `version` is present and does not match the current `Account.version` on the server, the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted from the request body, the server processes the mutation without an OCC check. After any successful mutation the resource's `version` increments by one and `updated_at` is refreshed.

### 2.8. Hierarchical Consistency and Cascades

The system maintains hierarchical invariants between an `Account`, the `Vehicle` resources it owns, and the `Transponder` resources bound to those vehicles. When an account becomes `SUSPENDED` because its outstanding fine total has crossed the suspension threshold, every `Vehicle` owned by that account is cascaded to `BLOCKED`, and every `Transponder` whose status is `ACTIVE` and owned by that account is cascaded to `SUSPENDED`. When the same account later returns to `ACTIVE` because its outstanding fines fell below the threshold, the cascade reverses: each `Vehicle` whose only reason for being `BLOCKED` was the account suspension is restored to `ACTIVE`, and each `SUSPENDED` `Transponder` is restored to `ACTIVE` provided it remains bound to a vehicle that is itself `ACTIVE`. Each such cascade is a mutation in its own right and individually increments the affected resource's `version` and refreshes its `updated_at`. Closing an account is a manual action that transitions it to `CLOSED` (a terminal state) and cascades all of its vehicles to `BLOCKED`; the precondition checks that make this safe live in §3.

A second class of cascade ties `TollEvent`, `Violation`, `Fine`, and `Account` together. Voiding a `TollEvent` whose `billing_status` is `POSTED` or `TOLL_BY_PLATE_INVOICED` refunds the prior debit by adding `net_toll_cents` back to `Account.balance_cents` and resetting both `gross_toll_cents` and `net_toll_cents` to zero. Voiding a `TollEvent` whose `billing_status` is `VIOLATED` clears the associated `Violation` (its `status` becomes `CLEARED`) and dismisses the associated `Fine` (its `settlement_status` becomes `DISMISSED`). Whenever any fine moves to a settled, dismissed, or disputed state — or whenever a new fine is created — `Account.outstanding_fine_cents` is recomputed, which may in turn move the owning account between `ACTIVE` and `SUSPENDED`.

### 2.9. Cross-Agency Interoperability

The network operates across four tolling agencies whose agency codes are `NY_EZPASS`, `NJ_EZPASS`, `PA_TURNPIKE`, and `FL_SUNPASS`. When the gantry's `agency_code` matches the account's `home_agency_code` no interoperability adjustment is made. When the two differ, the server consults `InteropPolicy` rows keyed by `(home_agency, gantry_agency)` and applies a surcharge expressed in basis points (`surcharge_bps`) and a discount expressed in basis points (`discount_bps`); the algorithm uses the *net* of the two — surcharge minus discount — applied as a fraction of `gross_toll_cents` (each basis point being one ten-thousandth). If more than one `InteropPolicy` row matches the `(home_agency, gantry_agency)` pair, the system uses the row with the most recent `created_at`, but the request that produced the lookup is rejected with `ERR_INTEROP_POLICY_AMBIGUOUS` so the operator is notified of the data condition.

### 2.10. Concurrency and Idempotency

Several operations in this domain race naturally and must therefore be serialized deterministically. Two simultaneous bind attempts targeting the same `Vehicle` from different `Transponder` resources serialize first-writer-wins on the vehicle's binding slot: the first attempt succeeds and the loser is rejected with `ERR_VEHICLE_ALREADY_BOUND`. A `Fine` racing between payment and dispute, or between void-via-toll-event and pay, serializes first-writer-wins on `Fine.settlement_status`, and the loser receives `ERR_INVALID_STATE`. Two `TollEvent` ingests that share the same `gantry_id`, the same `read_at` minute (the `read_at` timestamp truncated to the minute), and the same `plate_number` + `plate_state` or `transponder_serial` tuple serialize first-writer-wins on that deduplication tuple; the second ingest is rejected with `ERR_DUPLICATE_TOLL_EVENT`. A concurrent `PATCH` on an `Account` carrying a stale `version` is rejected with `ERR_VERSION_CONFLICT`. Finally, when two postings against the same account both observe a post-debit balance at or below the auto-reload threshold within the same minute, only one auto-reload is permitted to credit the account in that minute; the second posting observes the already-credited balance no longer at or below the threshold and does not reload. If two postings nonetheless both attempt to credit within the same minute, the loser is rejected with `ERR_RELOAD_ALREADY_RUNNING`.

### 2.11. Validation Priority

When more than one validation could plausibly reject a single request, the server evaluates checks in a fixed priority order so that error reporting is stable. Authentication is enforced first: presence of `X-User-ID` and `X-User-Role` (`ERR_MISSING_AUTH`), then validity of the role string (`ERR_INVALID_ROLE`), then role-to-endpoint authorization (`ERR_FORBIDDEN`). Path resources are then resolved left-to-right (`ERR_NOT_FOUND`). For `AccountHolder` requests, ownership is checked next so a holder cannot reach into another account's resources (`ERR_FORBIDDEN`). State-machine preconditions follow: an account must be `ACTIVE` to register a vehicle, bind a transponder, ingest a toll attributed to the account, or pay a fine (`ERR_ACCOUNT_NOT_ACTIVE`); a transponder must be in the correct state for the requested transition (`ERR_INVALID_STATE`); a fine must be in the correct settlement status for the requested action (`ERR_INVALID_STATE`); a toll event must be in the correct billing status for a void (`ERR_INVALID_STATE`). Business-safety checks come next — a blocked vehicle cannot be bound to a transponder or attributed to a toll (`ERR_VEHICLE_BLOCKED`), and a fraudulent HOV claim is recorded (`ERR_HOV_FRAUD_RECORDED`); the ambiguous `InteropPolicy` condition raises `ERR_INTEROP_POLICY_AMBIGUOUS` at the lookup step. Business-constraint checks then enforce uniqueness and limits: only one `ACTIVE` transponder per vehicle (`ERR_VEHICLE_ALREADY_BOUND`), duplicate toll-event ingest (`ERR_DUPLICATE_TOLL_EVENT`), and the dispute cap (`ERR_DISPUTE_LIMIT_REACHED`). Business-temporal checks govern the void window (`ERR_VOID_WINDOW_EXPIRED`), and business-fiscal checks govern manual reload amounts (`ERR_INVALID_RELOAD_AMOUNT`), account-closure obligations (`ERR_ACCOUNT_HAS_OBLIGATIONS`), plate-bill solvency (`ERR_INSUFFICIENT_FUNDS_ON_PLATE_BILL`), and resource uniqueness for transponder serials and plate pairs (`ERR_DUPLICATE_RESOURCE`). Generic field-level shape or range failures surface as `ERR_VALIDATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Account Onboarding, Configuration, and Closure

An `AgencyAdmin` creates a new account by supplying the customer's `holder_name` (between 1 and 120 characters in length) and a `home_agency_code` chosen from `NY_EZPASS`, `NJ_EZPASS`, `PA_TURNPIKE`, or `FL_SUNPASS`. At creation time the operator may opt the account into low-balance auto-replenishment by setting `auto_reload_enabled` to `true` and providing the `payment_method_token` that future reloads will charge; the token is a required input whenever auto-reload is enabled. Two numeric knobs govern the replenishment behavior: `auto_reload_threshold_cents`, the breakpoint at or below which the system will automatically credit the account, accepts any integer from 0 through 10000 inclusive and defaults to 1000; `auto_reload_topup_cents`, the credit amount, accepts any integer from 1000 through 20000 inclusive and defaults to 4000. A new account begins in the `ACTIVE` state with `balance_cents` of 0 and `outstanding_fine_cents` of 0.

Both an `AccountHolder` and an `AgencyAdmin` may amend the auto-reload knobs and the `payment_method_token` later; the same `version` field discussed in §2.7 makes the mutation safe under concurrent edits. A read of the account through either the regular fetch or the dedicated summary view returns the same `Account` shape, including the live `balance_cents`, `outstanding_fine_cents`, and `status` values. The summary view exists so that an account holder can see balance, outstanding fines, and a count of associated vehicles and transponders in a single round trip.

Closing an account requires the operator to deliberately invoke the close action with the account holder's affairs in order. The transition from `ACTIVE` to `CLOSED` is permitted only when `outstanding_fine_cents` is exactly 0 *and* no transponder owned by the account is in `ACTIVE` or `SUSPENDED` status — every transponder on the account must be either `UNBOUND` or `RETURNED`. Otherwise the request is rejected with `ERR_ACCOUNT_HAS_OBLIGATIONS`. On a successful close the account transitions to `CLOSED` and every vehicle owned by the account cascades to `BLOCKED`. `CLOSED` is terminal.

### 3.2. Vehicles and Transponders

A customer's vehicles are registered against their account by submitting a `plate_number` (1 to 10 characters drawn from the set of uppercase letters, digits, and dashes), the issuing `plate_state` (one of `NY`, `NJ`, `PA`, `FL`, `CA`, `TX`, or `OTHER`), an optional `axle_count` between 2 and 7 (defaulting to 2), and an optional `hov_capable` flag (defaulting to true) indicating whether the vehicle is eligible to claim an HOV exemption. The combination of `plate_number` and `plate_state` is unique across the entire network; an attempt to register a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`. The system derives `vehicle_class` from the `axle_count` using a tiered lookup: 2 axles correspond to `CLASS_2`, 3 axles to `CLASS_3`, 4 axles to `CLASS_4`, and 5 or more axles to `CLASS_5_PLUS`. A newly registered vehicle is `ACTIVE`; it becomes `BLOCKED` only via the cascades described in §2.8 or via the violation-escalation path described in §3.5.

Transponders are physical devices the agency ships to the customer. Registering one requires submitting only the manufacturer `serial_number` (between 10 and 24 characters of uppercase letters and digits) which must be globally unique across the system; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`. A freshly registered transponder begins in `UNBOUND` status with `bound_vehicle_id` of null and `bound_at` of null. Binding the transponder to one of the account's vehicles transitions it from `UNBOUND` to `ACTIVE`: the bind request carries the target `vehicle_id`, and the operation requires that the transponder's owning account match the path account, that the target vehicle exists and is owned by the same account, that the vehicle's status is `ACTIVE`, that the account's status is `ACTIVE`, and that no other transponder is presently bound to the same vehicle. The first four of those preconditions, when violated, surface as `ERR_FORBIDDEN`, `ERR_NOT_FOUND`, `ERR_VEHICLE_BLOCKED`, and `ERR_ACCOUNT_NOT_ACTIVE` respectively (see §2.11 for the evaluation order); the last surfaces as `ERR_VEHICLE_ALREADY_BOUND`. A successful bind records the target as `bound_vehicle_id` and stamps `bound_at` with the current UTC instant.

The reverse action, unbinding, transitions an `ACTIVE` transponder back to `UNBOUND`, clearing both `bound_vehicle_id` and `bound_at` to null. Unbinding requires the transponder to be currently `ACTIVE`; an attempt to unbind a transponder in any other state is rejected with `ERR_INVALID_STATE`. A transponder that is `UNBOUND` may be permanently retired by an account holder or admin, which transitions it to the terminal `RETURNED` state and excludes it from any future bind attempt; the precondition is again that the transponder must currently be `UNBOUND`. A transponder that has been suspended through the account-suspension cascade re-acquires `ACTIVE` status only when its owning account returns to `ACTIVE` *and* it is still bound to a vehicle whose own status is `ACTIVE` (the bound vehicle's id is not null and that vehicle is itself `ACTIVE`); otherwise the transponder remains `SUSPENDED` pending the next reconciliation.

### 3.3. Toll Event Ingestion, Attribution, and Pricing

Toll events are posted into the system by a `GantryOperator` as a single composite payload describing one passage of one vehicle through one gantry. The payload carries the `gantry_id` (an operator-defined string 1 to 32 characters in length), the operating `agency_code` (one of the four agency codes), the gantry's posted `base_rate_cents` at the moment of capture (a non-negative integer expressed in Class-2 reference terms), and the `read_at` ISO 8601 UTC timestamp of the gantry read. Up to three additional fields describe what the gantry actually observed: an optional `transponder_serial` if a transponder was read, and an optional `plate_number` together with its `plate_state` if the camera resolved a plate. The HOV pathway is described by two further fields — `hov_lane`, a boolean default `false` indicating the gantry sits in an HOV lane, and `declared_occupants`, an integer between 1 and 9 inclusive defaulting to 1 (the single-occupancy-vehicle case). Every freshly ingested event begins with `billing_status` of `PENDING`, with `account_id`, `vehicle_id`, and `capture_method` all null/unset, and with both `gross_toll_cents` and `net_toll_cents` at 0; the `hov_exempt_applied` flag begins false.

Attribution is resolved first. When the `transponder_serial` corresponds to a transponder whose status is `ACTIVE`, the gantry read is treated as a transponder capture: `capture_method` becomes `TRANSPONDER` and the associated `account_id` and `vehicle_id` are filled from the transponder's binding. If the `transponder_serial` is null or does not match any `ACTIVE` transponder, the system tries to attribute via plate by looking up the `plate_number` and `plate_state` against registered vehicles. A successful plate lookup sets `capture_method` to `PLATE` and fills `account_id` and `vehicle_id` from the resolved vehicle. When neither attribution path succeeds, `capture_method` becomes `UNRESOLVED` and `account_id` and `vehicle_id` remain null.

Once attribution is fixed the system computes the toll in a strictly pinned order. First, a class multiplier is selected from the table that maps `CLASS_2` to 1.00, `CLASS_3` to 1.50, `CLASS_4` to 2.25, and `CLASS_5_PLUS` to 3.50; `gross_toll_cents` is the gantry's `base_rate_cents` multiplied by that class multiplier, with the product rounded half up to whole cents. Second, an interoperability adjustment is computed: when the account's `home_agency_code` equals the gantry's `agency_code` the adjustment is zero, otherwise the `InteropPolicy` row keyed by `(home_agency, gantry_agency)` supplies `surcharge_bps` and `discount_bps`, and the adjustment is `gross_toll_cents` multiplied by the difference between `surcharge_bps` and `discount_bps` divided by ten thousand, again rounded half up to whole cents at this step. Third, when `capture_method` is `PLATE`, a plate-bill surcharge of fifteen percent of `gross_toll_cents` is added — concretely, `gross_toll_cents` multiplied by 1500 basis points (that is, 1500 divided by 10000), rounded half up to whole cents at this step; when `capture_method` is `TRANSPONDER` the plate-bill surcharge is zero. Finally, if the HOV exemption applies (see below), `net_toll_cents` is forced to zero regardless of what the prior additions produced; otherwise `net_toll_cents` is the sum of `gross_toll_cents`, the interoperability adjustment, and the plate-bill surcharge, with a floor of zero (the net toll is never negative).

The HOV exemption applies only when the gantry's `hov_lane` is true *and* the `declared_occupants` is at least 3 *and* the attribution-resolved vehicle's `hov_capable` is true. When all three conditions hold, the event transitions from `PENDING` to `EXEMPTED`: `hov_exempt_applied` becomes true, both `gross_toll_cents` and `net_toll_cents` are written as zero, and `capture_method` reflects whichever attribution path succeeded. When the gantry is an HOV lane and the claim does not satisfy all three conditions — for example because `declared_occupants` is less than 3 even though `hov_capable` is true — the event is treated as HOV fraud: a violation and fine are recorded and the request returns a 409 with `ERR_HOV_FRAUD_RECORDED` (the response envelope is the error shape but the persisted `Violation` and `Fine` remain). If the duplicate-event check fires first (same `gantry_id`, same `read_at` truncated to the minute, same plate or transponder), the operator instead sees `ERR_DUPLICATE_TOLL_EVENT`.

When attribution is resolved and the HOV exemption does not apply, three terminal billing outcomes are possible. If the capture is a `TRANSPONDER` read and the post-debit balance would land no lower than the negative of the auto-reload top-up amount (or `auto_reload_enabled` is true), the event transitions from `PENDING` to `POSTED`: the system writes `capture_method` as `TRANSPONDER`, decrements `Account.balance_cents` by `net_toll_cents`, and — described in §3.4 — may trigger an auto-reload. The bound vehicle must itself be `ACTIVE` and the owning account must itself be `ACTIVE` for the posting to succeed; otherwise the event becomes a violation as described next.

If the capture is a `PLATE` read against a resolved `Vehicle` whose owning `Account` is `ACTIVE` and the post-debit balance would land at zero or above (or `auto_reload_enabled` is true), the event transitions from `PENDING` to `TOLL_BY_PLATE_INVOICED` with `capture_method` set to `PLATE`. The plate-bill surcharge of fifteen percent applies, so a plate capture is more expensive than the equivalent transponder capture. The account is debited and the auto-reload cascade may run, exactly as in the transponder case.

If attribution fails entirely (no transponder match and no plate match), or if a plate-bill ingest would push the balance below zero with `auto_reload_enabled` set to false, or if the attribution-resolved vehicle is `BLOCKED`, or if the gantry is an HOV lane and the claim falls short of the three HOV conditions while `hov_capable` is true, the event transitions from `PENDING` to `VIOLATED`. The `capture_method` is recorded as `PLATE` when a plate was matched and `UNRESOLVED` otherwise. A `Violation` is created with a `reason_code` chosen from `UNREAD_TRANSPONDER_NO_PLATE` (no transponder match and no plate match), `INSUFFICIENT_FUNDS_ON_PLATE_BILL` (plate match but post-debit balance below zero without auto-reload), `BLOCKED_VEHICLE` (the attribution-resolved vehicle was `BLOCKED`), or `HOV_FRAUD` (the HOV claim failed). A `Fine` is created against that violation as described in §3.5, and the owning account's `outstanding_fine_cents` is recomputed (which may move the account between `ACTIVE` and `SUSPENDED`). Toll events are filterable on retrieval by `account_id`, `vehicle_id`, `billing_status`, `agency_code`, and `capture_method`.

An `AgencyAdmin` may void a toll event by referencing the event's id, but only within 24 hours of its `created_at`; outside this window the request is rejected with `ERR_VOID_WINDOW_EXPIRED`. A void is permitted only from `POSTED`, `TOLL_BY_PLATE_INVOICED`, or `VIOLATED`; in any other billing status the request is rejected with `ERR_INVALID_STATE`. Voiding a `POSTED` or `TOLL_BY_PLATE_INVOICED` event refunds the prior debit by adding `net_toll_cents` back to the balance and resetting both `net_toll_cents` and `gross_toll_cents` to zero. Voiding a `VIOLATED` event is permitted only while the associated fine's settlement status is still `PENDING`; the void cascades the associated `Violation` to `CLEARED` and the associated `Fine` to `DISMISSED`, and the owning account's `outstanding_fine_cents` is recomputed (potentially flipping the account from `SUSPENDED` back to `ACTIVE`).

### 3.4. Balance Maintenance and Auto-Reload

Account balances are denominated in integer cents and surfaced through `balance_cents`. After a successful settlement of any toll event the balance may momentarily go negative if the posting overshoots; the auto-reload step that immediately follows is designed to restore solvency on `auto_reload_enabled` accounts. Every reload — whether manually issued by a holder or automatically triggered by the system — is recorded as a `ReloadEvent` carrying its `kind` (`MANUAL` or `AUTO`), the credited `amount_cents`, the immediately-before snapshot `balance_before_cents`, and the immediately-after snapshot `balance_after_cents`. An `AUTO` reload additionally carries the originating toll event's id in `triggered_by_event_id`; a `MANUAL` reload leaves that field null. Reload history is retrievable per account and can be filtered by `kind`.

The auto-reload behavior runs as a side-effect of the same transaction that debits the account on a `POSTED` or `TOLL_BY_PLATE_INVOICED` event. The check is evaluated *after* the debit completes: when `auto_reload_enabled` is true and the post-debit `balance_cents` is at or below `auto_reload_threshold_cents` (the comparison is inclusive — a balance exactly equal to the threshold triggers a reload), the system creates a `ReloadEvent` with `kind` of `AUTO`, sets the credited `amount_cents` to the account's `auto_reload_topup_cents`, captures `balance_before_cents` as the post-debit value, adds `auto_reload_topup_cents` to `balance_cents`, and captures `balance_after_cents` as the credited value. The per-minute serialization guarantee from §2.10 ensures that two postings landing within the same minute do not both trigger reloads.

Manual reloads are initiated by an `AccountHolder` or `AgencyAdmin` against a specific account. The request body carries only `amount_cents`, which must be an integer between 100 and 50000 inclusive; any value outside this range is rejected with `ERR_INVALID_RELOAD_AMOUNT`. A successful manual reload adds the supplied amount to `balance_cents` and records a `ReloadEvent` with `kind` of `MANUAL`, `balance_before_cents` snapshotting the pre-credit balance, `balance_after_cents` snapshotting the post-credit balance, and `triggered_by_event_id` null.

### 3.5. Violations, Fines, and Vehicle Escalation

Every `Violation` is uniquely tied to the `toll_event_id` that produced it — at most one violation per toll event. The violation carries `account_id` and `vehicle_id` populated from the plate lookup (both remain null if no plate matched), the `reason_code` that classified the breach, and a `status` that begins at `OPEN`. The violation moves to `CLEARED` whenever its associated fine reaches a terminal benign outcome — either `SETTLED` because the holder paid or `DISMISSED` because the operator voided the event or upheld the dispute. The violation moves to the terminal `ESCALATED` state when the associated fine is `OVERDUE` and its `dispute_count` has reached 2; this escalation cascades by setting the affected vehicle's status to `BLOCKED` (a registration hold) and, when an account is associated and is currently `ACTIVE`, recomputing the account's outstanding fine total which may flip the account to `SUSPENDED`.

The `Fine` itself is parented to the `Violation`. Its `amount_cents` is the sum of a toll component and a `civil_penalty_cents` component. The toll component is computed by running the same pricing algorithm described in §3.3 but in its plate-bill variant — that is, with the fifteen-percent plate-bill surcharge applied regardless of how the original event was attributed, so an `UNRESOLVED` event still produces a representative toll figure when it can; the per-step rounding rules of §2.6 govern. The civil penalty floor is determined by the `reason_code`: an `UNREAD_TRANSPONDER_NO_PLATE` violation incurs a civil penalty of 5000 cents, an `INSUFFICIENT_FUNDS_ON_PLATE_BILL` violation incurs 2500 cents, a `BLOCKED_VEHICLE` violation incurs 7500 cents, and an `HOV_FRAUD` violation incurs 10000 cents. The two components are summed in integer cents to populate `amount_cents`, and `civil_penalty_cents` is recorded separately on the fine. The fine is stamped with `issued_at` matching the violation's creation time and `due_at` exactly thirty days after `issued_at`. Its initial `settlement_status` is `PENDING` and its `dispute_count` is 0.

The system reconciles `Account.outstanding_fine_cents` by summing the `amount_cents` of every fine tied to the account whose `settlement_status` is `PENDING` or `OVERDUE`; fines whose status is `DISPUTED`, `SETTLED`, or `DISMISSED` do not contribute (a `DISPUTED` fine counts as zero outstanding). When that total reaches or exceeds 15000 cents — the suspension threshold — and the account is currently `ACTIVE`, the account transitions to `SUSPENDED` with the cascades described in §2.8. When the total later falls back below 15000 cents and the account is currently `SUSPENDED`, the account returns to `ACTIVE` with the reverse cascades.

### 3.6. Paying, Disputing, and Adjudicating Fines

An `AccountHolder` who acknowledges a fine pays it by referencing the fine and supplying a `payment_method_token`. The fine must be in `PENDING` or `OVERDUE` settlement status; any other status is rejected with `ERR_INVALID_STATE`. A successful payment moves the fine to the terminal `SETTLED` status, cascades the associated violation to `CLEARED`, subtracts the fine's `amount_cents` from `Account.outstanding_fine_cents`, and — if the violation was previously `ESCALATED` — restores the affected vehicle from `BLOCKED` to `ACTIVE`. The outstanding-fine recomputation may then flip the account from `SUSPENDED` back to `ACTIVE`.

The account holder may instead contest a `PENDING` fine by opening a dispute with an explanatory `reason` string. A new dispute is permitted only when the fine's `dispute_count` is strictly less than 2; an attempt to open a third dispute is rejected with `ERR_DISPUTE_LIMIT_REACHED`. Opening a dispute moves the fine from `PENDING` to `DISPUTED`, increments `dispute_count` by one, and recomputes the account's outstanding fine total (because a `DISPUTED` fine contributes zero), which may flip the account from `SUSPENDED` to `ACTIVE` while the dispute is pending.

An `AgencyAdmin` adjudicates a `DISPUTED` fine in one of two ways. Upholding the dispute is the consumer-favorable resolution: the fine moves from `DISPUTED` to the terminal `DISMISSED` state, the associated violation cascades to `CLEARED`, the associated toll event's `net_toll_cents` remains zero (no separate refund occurs because the violation pathway never debited the account), and `outstanding_fine_cents` is recomputed. Rejecting the dispute returns the fine from `DISPUTED` back to `PENDING`; this re-applies the fine's `amount_cents` to the account's outstanding total (because `PENDING` fines count), and may flip the account from `ACTIVE` to `SUSPENDED`.

Beyond these manual paths, two side conditions move fines automatically. When the logical clock advances past a fine's `due_at` and the fine is still `PENDING`, an automatic sweep transitions it to `OVERDUE`. The sweep adds a late penalty of 2000 cents to both `amount_cents` and `civil_penalty_cents` (the fine compounds), recomputes the account's outstanding total which may flip the account to `SUSPENDED`, and — if the fine's `dispute_count` is at 2 already — cascades the associated `Violation` from `OPEN` to `ESCALATED` (placing a registration hold on the affected vehicle by setting its status to `BLOCKED`). The same overdue sweep is also reachable on demand without advancing the clock, which exists purely to give operators a deterministic way to drive the system through a sweep cycle on the current instant. Paying an `OVERDUE` fine settles it in the same way as paying a `PENDING` fine: the violation cascades to `CLEARED`, an escalated vehicle is restored from `BLOCKED` to `ACTIVE`, the fine's full `amount_cents` (including the accrued late penalty) is subtracted from `outstanding_fine_cents`, and the account may flip from `SUSPENDED` to `ACTIVE`. A fine that is `DISMISSED` automatically as a consequence of voiding the originating toll event cascades the associated violation to `CLEARED` and subtracts the fine's `amount_cents` from `outstanding_fine_cents`, with the same possible account-status flip. Fines are listable and filterable by `account_id` and `settlement_status`.

### 3.7. Interop Policy Maintenance and the Logical Clock

Cross-state pricing relies on `InteropPolicy` rows maintained by `AgencyAdmin` operators. Each row carries a `home_agency` and a `gantry_agency` chosen from the four agency codes, a `surcharge_bps` between 0 and 5000 inclusive defaulting to 0, and a `discount_bps` between 0 and 5000 inclusive defaulting to 0. Policy rows are immutable events of record — they carry only `id` and `created_at`. Listing accepts optional `home_agency` and `gantry_agency` filters in addition to the usual pagination parameters. The lookup at pricing time joins on `(home_agency, gantry_agency)`; the ambiguous-row escape in §2.9 governs the multi-match condition.

Two test-driving capabilities are exposed under an admin-only namespace to make overdue-related test cases reachable. The first advances the system's logical clock to a supplied `to_iso8601` instant, which immediately triggers the `PENDING` → `OVERDUE` sweep over any fine whose `due_at` is at or before the new clock value, with all the cascades described in §3.6. The second runs the same sweep at the current clock value without changing the clock; it exists to let test orchestration drive the sweep deterministically without time-skewing the rest of the system. Both capabilities accept no auth from holders or gantry operators — they are reserved to `AgencyAdmin`.

## 4. Endpoint Definitions

Operations that create a new resource (such as an account, a vehicle, a transponder, a reload, an interop policy, or a toll event) return `201 Created`. Operations that update or transition an existing resource — including bind, unbind, void, pay, dispute, and dispute adjudication — return `200 OK`. Destructive operations that result in no body (closing an account, returning an unbound transponder) return `204 No Content`. List and read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/accounts`                                                                  | Create a new account                                          | AgencyAdmin                              |
| GET    | `/accounts/{account_id}`                                                     | Retrieve an account by id                                     | AccountHolder, AgencyAdmin               |
| PATCH  | `/accounts/{account_id}`                                                     | Update account settings (auto-reload, payment token); OCC     | AccountHolder, AgencyAdmin               |
| DELETE | `/accounts/{account_id}`                                                     | Close an account                                              | AgencyAdmin                              |
| GET    | `/accounts`                                                                  | List accounts                                                 | AgencyAdmin                              |
| GET    | `/accounts/{account_id}/summary`                                             | Account summary view                                          | AccountHolder, AgencyAdmin               |
| POST   | `/accounts/{account_id}/vehicles`                                            | Register a vehicle on an account                              | AccountHolder, AgencyAdmin               |
| GET    | `/accounts/{account_id}/vehicles/{vehicle_id}`                               | Retrieve a vehicle                                            | AccountHolder, AgencyAdmin               |
| GET    | `/accounts/{account_id}/vehicles`                                            | List vehicles for an account                                  | AccountHolder, AgencyAdmin               |
| POST   | `/accounts/{account_id}/transponders`                                        | Register a transponder                                        | AccountHolder, AgencyAdmin               |
| POST   | `/accounts/{account_id}/transponders/{transponder_id}/bind`                  | Bind a transponder to a vehicle                               | AccountHolder, AgencyAdmin               |
| POST   | `/accounts/{account_id}/transponders/{transponder_id}/unbind`                | Unbind a transponder                                          | AccountHolder, AgencyAdmin               |
| DELETE | `/accounts/{account_id}/transponders/{transponder_id}`                       | Return (decommission) an UNBOUND transponder                  | AccountHolder, AgencyAdmin               |
| POST   | `/accounts/{account_id}/reloads`                                             | Manual reload                                                 | AccountHolder, AgencyAdmin               |
| GET    | `/accounts/{account_id}/reloads`                                             | List reload history                                           | AccountHolder, AgencyAdmin               |
| POST   | `/toll-events`                                                               | Ingest a gantry toll event                                    | GantryOperator                           |
| GET    | `/toll-events/{toll_event_id}`                                               | Retrieve a toll event                                         | AccountHolder, AgencyAdmin, GantryOperator |
| GET    | `/toll-events`                                                               | List toll events                                              | AccountHolder, AgencyAdmin               |
| POST   | `/toll-events/{toll_event_id}/void`                                          | Operator void of a toll event                                 | AgencyAdmin                              |
| GET    | `/fines/{fine_id}`                                                           | Retrieve a fine                                               | AccountHolder, AgencyAdmin               |
| GET    | `/fines`                                                                     | List fines                                                    | AccountHolder, AgencyAdmin               |
| POST   | `/fines/{fine_id}/pay`                                                       | Pay a fine                                                    | AccountHolder                            |
| POST   | `/fines/{fine_id}/dispute`                                                   | Open a dispute against a fine                                 | AccountHolder                            |
| POST   | `/fines/{fine_id}/dispute/uphold`                                            | Uphold a dispute (Fine → DISMISSED)                           | AgencyAdmin                              |
| POST   | `/fines/{fine_id}/dispute/reject`                                            | Reject a dispute (Fine → PENDING)                             | AgencyAdmin                              |
| POST   | `/interop-policies`                                                          | Create an interop policy                                      | AgencyAdmin                              |
| GET    | `/interop-policies`                                                          | List interop policies                                         | AgencyAdmin, GantryOperator              |
| POST   | `/_clock/advance`                                                            | Advance system clock                                          | AgencyAdmin                              |
| POST   | `/_sweep/run`                                                                | Run the OVERDUE sweep at the current clock                    | AgencyAdmin                              |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH`                  | 401 Unauthorized |
| `ERR_INVALID_ROLE`                  | 401 Unauthorized |
| `ERR_FORBIDDEN`                     | 403 Forbidden    |
| `ERR_NOT_FOUND`                     | 404 Not Found    |
| `ERR_DUPLICATE_RESOURCE`            | 409 Conflict     |
| `ERR_VEHICLE_ALREADY_BOUND`         | 409 Conflict     |
| `ERR_INVALID_STATE`                 | 409 Conflict     |
| `ERR_ACCOUNT_NOT_ACTIVE`            | 409 Conflict     |
| `ERR_VEHICLE_BLOCKED`               | 409 Conflict     |
| `ERR_INSUFFICIENT_FUNDS_ON_PLATE_BILL` | 409 Conflict  |
| `ERR_HOV_FRAUD_RECORDED`            | 409 Conflict     |
| `ERR_DUPLICATE_TOLL_EVENT`          | 409 Conflict     |
| `ERR_VOID_WINDOW_EXPIRED`           | 409 Conflict     |
| `ERR_DISPUTE_LIMIT_REACHED`         | 409 Conflict     |
| `ERR_VERSION_CONFLICT`              | 409 Conflict     |
| `ERR_RELOAD_ALREADY_RUNNING`        | 409 Conflict     |
| `ERR_INTEROP_POLICY_AMBIGUOUS`      | 422 Unprocessable Entity |
| `ERR_INVALID_RELOAD_AMOUNT`         | 422 Unprocessable Entity |
| `ERR_ACCOUNT_HAS_OBLIGATIONS`       | 409 Conflict     |
| `ERR_VALIDATION`                    | 422 Unprocessable Entity |
