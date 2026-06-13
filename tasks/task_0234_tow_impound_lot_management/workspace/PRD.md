# Tow & Impound Lot Management API — Product Requirements Document

## 1. Introduction

When a vehicle is towed — at the direction of police, by a private property owner, or because it has been abandoned — it enters a regulated chain of custody that ends only when its owner reclaims it, a lienholder is made whole, or the jurisdiction sells it at a statutory-period auction. This API governs that entire chain of custody for an operator running one or more impound lots. It tracks every order from the moment a vehicle rolls onto the lot, accrues storage fees day by day, drives the certified-mail and publication notices the law requires before a vehicle may be sold, decides who is owed what at release or sale, and adjudicates the fee waivers and disputes that owners file along the way.

The system is built around two intertwined disciplines. The first is **compliance and audit**: a vehicle cannot become auction-eligible until both a statutory holding period and a notice grace window have demonstrably elapsed, holds placed by law enforcement must be able to freeze an order in place, and the duty to decide a waiver must be segregated from the duty to file one. The second is **ledger reconciliation**: every fee is computed to the whole cent through a pinned, reproducible sequence, storage charges are accrued chronologically across freeze-and-resume boundaries without double-counting a single day, and auction proceeds are distributed through a deterministic waterfall in which every cent of a sale price is accounted for. The remainder of this document specifies the entities, lifecycles, calculations, and access rules that together make those two disciplines auditable and exact.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `LotOperator`, `PoliceOfficer`, `TowProvider`, `Claimant`, and `AuctionOfficial`.

A `LotOperator` is impound-lot staff who configures lots, providers, and lienholders, runs intake and accrual, sends notices, authorizes and records releases, dispatches rotation calls, and decides fee waivers. When `X-User-Role` is `LotOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `decided_by_user_id` on a `FeeWaiver` when the operator decides a waiver — but it does not compare it to any entity's `id`.

A `PoliceOfficer` is law enforcement who authorizes police and abandoned intake, places and lifts evidence or police holds, and voids wrongful tows. When `X-User-Role` is `PoliceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

A `TowProvider` is a rotation-list tow company that accepts or declines the rotation offers dispatched to it. When `X-User-Role` is `TowProvider`, `X-User-ID` is the `id` of the acting `TowProvider`; ownership checks on any resource that references a `TowProvider` compare the resource's foreign-key field to `X-User-ID`. Concretely, only the provider an offer was dispatched to may accept or decline it: the acting `X-User-ID` must equal that assignment's `provider_id`, and a mismatch is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

A `Claimant` is the vehicle owner or their agent, who files and withdraws fee waivers and disputes, records payments toward a balance, and reads order, notice, and inventory records. When `X-User-Role` is `Claimant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `filed_by_user_id` when the claimant files a waiver but does not compare it to any entity's `id`. The segregation rule that governs waiver decisions, and the rule that only the filer may withdraw a waiver, both operate by comparing the recorded `filed_by_user_id` against the acting `X-User-ID`.

An `AuctionOfficial` conducts statutory-period auctions: scheduling windows, opening them, sweeping eligible orders, recording and voiding sales, and settling. When `X-User-Role` is `AuctionOfficial`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with no upper bound.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every primary, top-level resource in the system — impound lots, tow providers, lienholders, rotation assignments, tow orders, notifications, inventory items, fee waivers, release records, and auctions — carries a standard set of system-managed fields. The `id` is a unique, server-minted identifier formatted as a UUID, with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment of creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every change to the resource's properties. The `version` field is an integer that begins at 1 on creation and increments by exactly 1 on every subsequent mutation of the resource; it is the basis for optimistic concurrency control described in §2.7.

One entity is the exception to this rule. The `StorageLedgerEntry`, which records an individual segment of storage accrual, is immutable once written and therefore carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. Whenever this document refers to "refreshing `updated_at`" or "bumping `version`," that instruction applies only to the resource being mutated and never to a `StorageLedgerEntry`.

Because storage accrual, statutory eligibility, and offer expiry are all time-gated, the server keeps a single logical UTC clock that determines what "now" means for every computation. An administrative, test-driving capability sets this clock to an explicit instant supplied as `to_iso8601`; from that point forward every reading of the current time — for accrual, for grace-window checks, for offer-expiry checks — uses the set value. The fields `intake_at`, `stored_at`, `accrual_frozen_at`, `offered_at`, `expires_at`, `sent_at`, `resolved_at`, and `authorized_at` are all stamped from this logical clock at the moment their triggering event occurs.

### 2.5. Nested Resource Retrieval and Referential Validation

Many resources are addressed through nested paths — a notification, an inventory item, a fee waiver, a release record, or a ledger entry all live beneath the tow order they concern. When a path contains more than one resource identifier, the server validates them in left-to-right order and rejects the request with `ERR_NOT_FOUND` for the first identifier in the path that does not correspond to an existing resource. A fee waiver requested under a non-existent tow order, for instance, fails on the tow order before the server ever looks for the waiver.

Beyond mere existence, several write operations assert that the foreign keys named in a request body are mutually consistent. When a tow order is created with a `rotation_assignment_id`, that assignment's `provider_id` must match the `provider_id` supplied on the order; a named `lienholder_id` must resolve to an existing lienholder; and the `lot_id` must be coherent with the other references. When these references resolve individually but contradict one another, the request is rejected with `ERR_REFERENCE_MISMATCH`. This referential-consistency check applies specifically to tow order creation, to notification sending, and to rotation dispatch.

### 2.6. Monetary and Day-Count Precision

All monetary amounts in the system are integer counts of cents; there are no fractional cents and no floating-point money. Where a calculation prescribes rounding — the per-component fee breakdown, the waiver cap, the proceeds waterfall — the precise method is stated with that calculation in §3, and in every case the result is a whole number of cents.

Storage is measured in whole calendar days. To convert an elapsed duration into days, the system takes the elapsed hours and divides by 24, then rounds **up** to the next whole day for any started day — that is, it applies a ceiling. The day boundary is strict on hours: a span of exactly 24.0 hours counts as 1 day, while a span of 24.01 hours counts as 2 days, because any fraction of a day beyond a completed day rolls into a full additional day. This ceiling-of-hours-over-24 rule is the single, consistent definition of "a day of storage" used everywhere accrual or statutory elapse is computed.

Standing percentages for providers are carried to two decimal places using the round-half-up method, never falling below 0.00 and never exceeding 100.00.

### 2.7. Optimistic Concurrency Control on Rotation Dispatch

Dispatching the next rotation call is the one operation in the system that advances a shared cursor on a parent resource, and it is therefore guarded by optimistic concurrency control. A dispatch request must carry `expected_lot_version` as a required field, holding the client's last-observed `version` of the target `ImpoundLot`. If `expected_lot_version` does not equal the lot's current `version` — because another dispatch has already advanced the lot's `rotation_cursor` and minted the next offer since the client last read the lot — the request is rejected with `ERR_STALE_LOT_VERSION` at HTTP status 412, preventing the caller from acting on a stale view of which provider is "next" and double-offering the slot. The same `expected_lot_version` field is required when suspending a lot, and a mismatch there likewise yields `ERR_STALE_LOT_VERSION` (HTTP 412). No other endpoint in the system takes a version field; only lot suspension and rotation dispatch participate in this check.

### 2.8. Holds as a Parallel Dimension

A tow order carries two independent state dimensions at once. Its `status` follows the lifecycle described in §3, while its `hold_status` is a separate axis with the values `NONE`, `POLICE_HOLD`, and `EVIDENCE_HOLD`. A hold is placed and lifted by a `PoliceOfficer` without regard to where the order sits in its lifecycle, and any non-`NONE` hold blocks the order's release and auction-sale transitions. The interaction between the two dimensions is detailed where each transition is described; the principle to hold throughout is that the hold dimension can independently veto progress on the status dimension without itself being part of that lifecycle.

### 2.9. Cascades, Reconciliation, and Append-Only Accrual

Several operations in this system mutate more than one resource at once, and every such cascade is specified in full where its triggering workflow is described in §3. Three patterns recur and are worth stating up front. First, accepting, declining, or expiring a rotation offer adjusts cumulative counters on the affected provider and triggers a recomputation of that provider's standing; a decline or an expiry additionally dispatches a fresh offer to the next eligible provider. Second, approving a fee waiver credits the parent tow order and forces a recomputation of the amount that order still owes. Third, recording or voiding an auction sale re-runs the proceeds waterfall on the parent auction. In every cascade, each resource that is mutated independently refreshes its own `updated_at` and increments its own `version`.

Storage accrual is recorded through an append-only series of `StorageLedgerEntry` rows rather than by overwriting a single running total. Each entry describes one continuous segment of accrual: its `segment_start` marks where the segment began and its `segment_end` marks the freeze instant that ended it, its `days_counted` is the whole days charged in that segment, and its `segment_charge_cents` is the cents charged for the segment — that is, `days_counted` multiplied by the lot's `daily_storage_rate_cents`. The order's reported `accrued_days` and `accrued_storage_cents` are always derived by summing `days_counted` and `segment_charge_cents` across these segments, so that freezing and resuming accrual never double-counts a day at the boundary.

## 3. Business Logic & Workflows

### 3.1. Configuring the Lot, the Rotation List, and Lienholders

Everything in the system hangs off an **impound lot**, the facility that physically stores vehicles and sets the fee schedule and statutory parameters that govern every order within it. A `LotOperator` creates a lot by supplying its `name`, a `jurisdiction_code` identifying the state or jurisdiction whose statutory rules apply, a `daily_storage_rate_cents` charged per calendar day to every order at the lot (which must be greater than zero), an `admin_fee_cents` flat processing fee charged once per order (which must be zero or greater), a `lien_processing_fee_cents` added when an order has a lienholder on record (zero or greater), a `statutory_hold_days` count of days a vehicle must be held from intake before it can become auction-eligible (at least 1), and a `notice_grace_days` count of days that must elapse after a notice is delivered before auction eligibility (zero or greater). The operator may also supply `max_provider_concurrent_offers`, the cap on how many simultaneously `OFFERED` rotation calls a single provider may hold at this lot; when omitted it defaults to 2 and must be at least 1. A new lot begins life with `status` of `OPEN`, with its `rotation_cursor` initialized to 0, and with `version` 1. The `rotation_cursor` is a system-maintained index into the ordered rotation list that points at the provider to be offered next.

A lot's `status` is either `OPEN` or `SUSPENDED`. Suspending a lot moves it to `SUSPENDED`, which blocks all new intake at that lot, and increments the lot's `version` by 1; because suspension changes the lot, it requires the caller to present the correct `expected_lot_version` as described in §2.7. A `SUSPENDED` lot continues to accrue storage and process releases on its existing orders — only fresh intake is barred.

Tow companies are registered as **providers** on the lot's rotation list by a `LotOperator`, who supplies the `company_name`, a `license_number` that must be unique across all providers, and a `rotation_rank` giving the provider's ordering position in the rotation list, where a lower rank is offered first; the rank must be at least 1 and is unique among `ACTIVE` providers. The operator may also supply `trailing_window_size`, the number of most-recent offers used by the trailing standing calculation, which defaults to 10 and must be at least 1. A new provider starts `ACTIVE` with its counters — `offers_received_count` and `offers_accepted_count` — at 0. A provider's `status` is either `ACTIVE` or `SUSPENDED`; only `ACTIVE` providers are eligible to receive rotation calls. Suspending a provider moves it to `SUSPENDED` and recomputes its standing with the suspension penalty applied; reinstating a `SUSPENDED` provider returns it to `ACTIVE` and recomputes its standing. A provider exposes two computed standing percentages, `raw_standing_pct` and `effective_standing_pct`, whose definitions are given in §3.7.

A **lienholder** — the bank or finance company holding a security interest in a towed vehicle — is recorded by a `LotOperator` with its legal `name`, a `mailing_address` to which certified statutory notices are sent, and a `state_code` for its state of record. Lienholders are simple reference records with no lifecycle of their own.

### 3.2. Rotation Dispatch and the Provider Selector

When a lot needs a tow performed, a `LotOperator` dispatches the next rotation call. Dispatch carries the required `expected_lot_version` and may carry `offer_ttl_minutes`, the number of minutes the chosen provider will have to accept before the offer lapses; `offer_ttl_minutes` defaults to 30 and must be at least 1. A successful dispatch selects the next eligible provider, mints a new `RotationAssignment` in status `OFFERED`, increments that provider's `offers_received_count` by 1, recomputes that provider's standing, and advances the lot's `rotation_cursor` by 1 (wrapping around the end of the rank-ordered list), as well as incrementing the lot's `version` by 1.

The selector that picks the provider is fully deterministic — there are no random fields. The candidate set is the lot's `ACTIVE` providers whose count of currently `OFFERED` rotation assignments is strictly fewer than the lot's `max_provider_concurrent_offers`. Among the candidates, the server scans the rank-ordered list starting from the position indicated by the lot's `rotation_cursor` and wrapping cyclically back to the start, and takes the first eligible provider at or after the cursor. Because `rotation_rank` is unique among `ACTIVE` providers there is normally no tie; should two providers nonetheless share a rank in the data, the earlier `created_at` wins, never the `id`. If the candidate set is empty — every active provider is already at its concurrent-offer cap, or there are no active providers — no offer is minted and the request is rejected with `ERR_NO_ELIGIBLE_PROVIDER`.

Each `RotationAssignment` records the `lot_id` of the dispatching lot, the server-selected `provider_id` the call was offered to, the `offered_at` instant the offer was dispatched (the current clock), and the `expires_at` instant computed as `offered_at` plus the offer's `offer_ttl_minutes`, past which the offer may be expired. It also carries an audit back-pointer, `superseded_by_id`, which is set by the re-offer cascade to the `id` of the replacement offer when this one is declined or expired, and is null otherwise. An assignment's `status` runs through `OFFERED`, `ACCEPTED`, `DECLINED`, `EXPIRED`, and `CANCELLED`.

A `TowProvider` accepts an offer it was dispatched. Acceptance is permitted only while the assignment is `OFFERED` (otherwise `ERR_INVALID_STATE`); only the offered provider may accept, meaning the acting `X-User-ID` must equal the assignment's `provider_id`, or the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`; the current clock must be at or before `expires_at`, or the request is rejected with `ERR_OFFER_EXPIRED`; and the provider must be `ACTIVE`, or the request is rejected with `ERR_PROVIDER_NOT_ACTIVE`. A successful accept moves the assignment `OFFERED → ACCEPTED`, increments the provider's `offers_accepted_count` by 1, and recomputes the provider's standing variants.

A `TowProvider` may instead decline an offer it holds; declining is allowed only from `OFFERED` (otherwise `ERR_INVALID_STATE`) and only by the offered provider, whose `X-User-ID` must equal the assignment's `provider_id` (otherwise `ERR_FORBIDDEN_FOR_ROLE`). A decline triggers a three-hop cascade: first this assignment moves `OFFERED → DECLINED`; second, the server advances the lot's `rotation_cursor` and dispatches a fresh `RotationAssignment` in `OFFERED` status to the next eligible provider under the same selector policy, and sets this declined row's `superseded_by_id` to the new assignment's `id`; third, the next provider's `offers_received_count` is incremented by 1 and that provider's standing is recomputed.

A `LotOperator` may expire an offer whose time-to-accept has run out. Expiry is allowed only from `OFFERED` (otherwise `ERR_INVALID_STATE`) and only when the current clock is strictly past `expires_at`; calling it before that instant is rejected with `ERR_OFFER_NOT_EXPIRED`. A successful expiry moves the assignment `OFFERED → EXPIRED` and runs the identical re-offer cascade as a decline — advancing the cursor, dispatching the next `OFFERED` offer, setting `superseded_by_id` on the expired row, and bumping the next provider's `offers_received_count` with a standing recomputation. A `LotOperator` may also cancel an offer outright; cancellation is allowed only from `OFFERED` (otherwise `ERR_INVALID_STATE`), moves the assignment `OFFERED → CANCELLED`, and dispatches no replacement offer. Rotation assignments can be listed and filtered by `provider_id`, `lot_id`, and `status` so an operator or a provider can trace the offer history.

### 3.3. Vehicle Intake and the Storage Lifecycle

A vehicle enters the system as a **tow order**, created by either a `LotOperator` or a `PoliceOfficer`. Intake supplies the `lot_id` of the storing lot, the `tow_type` (one of `POLICE`, `PRIVATE`, or `ABANDONED`), the vehicle's `vin` and `plate`, and the registered `owner_name` and `owner_address` to which notices will be sent. Intake may also supply a `provider_id` for the provider that performed the tow (left absent for an owner-arranged `PRIVATE` tow), a `rotation_assignment_id` identifying the `ACCEPTED` rotation call that produced this tow (absent when the tow was not rotation-dispatched), and a `lienholder_id` naming a recorded lienholder (absent when the vehicle is lien-free). The stated foreign keys must be mutually consistent per §2.5, failing with `ERR_REFERENCE_MISMATCH` otherwise, and the lot must be `OPEN`: intake against a `SUSPENDED` lot is rejected with `ERR_LOT_SUSPENDED`.

A new order is stamped with `intake_at` set to the current clock — day 0 of accrual — and begins in `status` `TOWED` with `hold_status` `NONE`. At intake the system fixes the order's `estimated_storage_cents`, a forward-looking ESTIMATE projection computed once and never re-counted: it is the lot's `daily_storage_rate_cents` multiplied by the lot's `statutory_hold_days`, ignoring how much time actually elapses. The order also carries the system-maintained `auction_id` (null until the order is auctioned) and `amount_paid_cents` (cumulative cents paid, starting at 0). The full `status` enumeration for a tow order is `TOWED`, `STORED`, `RELEASE_AUTHORIZED`, `RELEASED`, `AUCTION_ELIGIBLE`, `AUCTIONED`, and `VOIDED`, of which `RELEASED`, `AUCTIONED`, and `VOIDED` are terminal.

Before a vehicle can begin accruing storage it must be moved to `STORED` by a `LotOperator`. The transition `TOWED → STORED` requires the order to actually be in `TOWED` (otherwise `ERR_INVALID_STATE`) and requires at least one `InventoryItem` to have been documented for the order as intake evidence; storing an order with no inventory on file is rejected with `ERR_INVENTORY_REQUIRED`. On success the server stamps `stored_at` to the current clock (leaving `intake_at` unchanged), opens the first `StorageLedgerEntry` for the order with `kind` `ACCRUAL` and its `segment_start` at `stored_at` and an open (not-yet-set) `segment_end`, and recomputes the order's `accrued_storage_cents`, `balance_due_cents`, and `net_due_cents`.

Documentation of a vehicle's contents and condition lives in **inventory items**, each created by a `LotOperator` against a tow order with a `category` (one of `PERSONAL_PROPERTY`, `VEHICLE_DAMAGE`, or `EXTERIOR_PHOTO`), a free-text `description`, a `photo_ref` opaque storage reference for the documenting photograph, and an optional `condition_note` annotating the item's condition at intake. Inventory items can be listed for an order and filtered by `category`. As noted above, at least one inventory item is the precondition that gates the move into storage.

A `PoliceOfficer` may void a tow that should never have happened. Voiding is permitted only while the order's `status` is one of `TOWED` or `STORED` (otherwise `ERR_INVALID_STATE`); it moves the order to the terminal `VOIDED` state, zeroes all fee accrual, and closes any open `StorageLedgerEntry`. Independently of the lifecycle, a `PoliceOfficer` may place a hold: placing a hold is permitted only when the order's `status` is not already one of the terminal `RELEASED`, `AUCTIONED`, or `VOIDED` (otherwise `ERR_INVALID_STATE`) and only when `hold_status` is currently `NONE` (otherwise `ERR_HOLD_ACTIVE`); the request names the desired `hold_status`, moving it to `POLICE_HOLD` or `EVIDENCE_HOLD` as requested, after which release and auction transitions are blocked. Lifting a hold is permitted only when a hold is in fact active — if `hold_status` is already `NONE` the request is rejected with `ERR_NO_HOLD` — and returns `hold_status` to `NONE`, after which the status-dimension transitions become available again.

### 3.4. Statutory Notices to Owners and Lienholders

A vehicle cannot be sold until the parties with an interest in it have been notified and a grace period has run. The system models each notice as a **notification** created by a `LotOperator` against a tow order in `DRAFT` status, specifying a `recipient_type` (either `OWNER` or `LIENHOLDER`) and a delivery `method` (one of `CERTIFIED_MAIL`, `PUBLICATION`, or `EMAIL`). A notification records the `tow_order_id` it concerns and carries the audit field `republished_from_id`, a back-pointer to the `id` of the prior `UNDELIVERABLE` notice this one replaces (null for a first attempt). Notices can be listed for an order and filtered by `recipient_type` and `status`, and a single notice can be fetched directly. A notification's `status` runs through `DRAFT`, `SENT`, `DELIVERY_CONFIRMED`, `CERTIFIED_RETURNED`, and `UNDELIVERABLE`, of which `DELIVERY_CONFIRMED` and `CERTIFIED_RETURNED` are terminal.

Sending a notice moves it `DRAFT → SENT`, which is allowed only from `DRAFT` (otherwise `ERR_INVALID_STATE`); when the `recipient_type` is `LIENHOLDER`, the parent tow order must actually carry a `lienholder_id`, or the send is rejected with `ERR_NO_LIENHOLDER`. On send the server stamps `sent_at` to the current clock.

A `SENT` notice forks four ways, and each branch carries its own consequences. Confirming delivery moves it `SENT → DELIVERY_CONFIRMED` (allowed only from `SENT`, else `ERR_INVALID_STATE`); it stamps `resolved_at` to the current clock, which starts the notice grace clock running on the tow order, and recomputes the order's statutory eligibility. Marking a certified letter returned moves it `SENT → CERTIFIED_RETURNED` (allowed only from `SENT`, else `ERR_INVALID_STATE`) and is permitted only when the notice's `method` is `CERTIFIED_MAIL`, otherwise it is rejected with `ERR_METHOD_NOT_CERTIFIED`; a certified return counts as constructive delivery, so it too stamps `resolved_at` and starts the grace clock, and recomputes statutory eligibility. Marking a notice undeliverable moves it `SENT → UNDELIVERABLE` (allowed only from `SENT`, else `ERR_INVALID_STATE`); it stamps `resolved_at` but pointedly does **not** start the grace clock and leaves statutory eligibility unaffected, and the order must be re-noticed by `PUBLICATION` to make progress. `UNDELIVERABLE` is not terminal — it is a dead end that requires a republished notice. In short, only the `DELIVERY_CONFIRMED` and `CERTIFIED_RETURNED` branches advance the statutory clock; the `UNDELIVERABLE` branch does not.

### 3.5. Fees Owed at Release, and the Release Workflow

The amount owed to spring a vehicle is assembled from three independently-rounded whole-cent components, summed in a pinned order so that every evaluator arrives at the same total. The first component is the order's `accrued_storage_cents` (the chronological storage charge to date, already whole cents). The second is the lot's `admin_fee_cents`. The third is a lien-processing charge equal to the lot's `lien_processing_fee_cents` when the order has a `lienholder_id` on record, and zero when it does not. The order's `balance_due_cents` is the sum of those three components. Each component is whole cents in its own right, and the components are added in that fixed order — storage, then admin, then lien — never summed and then rounded; this per-component-then-sum contract guarantees the same `balance_due_cents` regardless of evaluator.

Against that pre-waiver balance the system applies any approved waiver. The order's `waiver_credit_cents` is the running total of approved fee-waiver credit, and its `net_due_cents` is `balance_due_cents` minus `waiver_credit_cents`, floored at zero so it is never negative. A `Claimant` or a `LotOperator` can record a payment toward the balance, supplying `amount_cents`; each recorded payment adds `amount_cents` to the order's `amount_paid_cents`.

Authorizing a release is a `LotOperator` action that moves the order `STORED → RELEASE_AUTHORIZED`. It is gated by four conditions evaluated together: the order must be in `STORED` (otherwise `ERR_INVALID_STATE`); the order's `hold_status` must be `NONE`, since an active hold blocks authorization with `ERR_HOLD_ACTIVE`; there must be no fee waiver on the order still in `REQUESTED` or `UNDER_REVIEW` status, since a pending waiver blocks authorization with `ERR_WAIVER_PENDING`; and the order's `amount_paid_cents` must be at least its `net_due_cents`, since an unsatisfied balance blocks authorization with `ERR_BALANCE_UNPAID`. On success the server freezes accrual: it closes the current open `StorageLedgerEntry` by setting its `segment_end` to the current clock with `kind` `FREEZE`, sets the order's `accrual_frozen_at` to that instant, and recomputes `accrued_storage_cents` and `balance_due_cents` to their final values at the freeze instant.

A release authorization can lapse. A `LotOperator` may lapse an authorization, moving the order `RELEASE_AUTHORIZED → STORED`; this is allowed only from `RELEASE_AUTHORIZED` (otherwise `ERR_INVALID_STATE`). Lapsing resumes accrual by opening a new `StorageLedgerEntry` with `kind` `RESUME` and its `segment_start` at the current clock, and clears the order's `accrual_frozen_at`. The compensating invariant is that `accrued_days` continues from its frozen value: no day is double-counted across the freeze-and-resume boundary, because accrual picks up from where the freeze left it rather than restarting.

Physically releasing the vehicle is recorded as a **release record** by a `LotOperator`, supplying the `amount_paid_cents` tendered for this release and the `released_to_name` of the person taking possession. Recording a release moves the order `RELEASE_AUTHORIZED → RELEASED` (the terminal released state) and is permitted only from `RELEASE_AUTHORIZED` (otherwise `ERR_INVALID_STATE`) and only when `hold_status` is `NONE` (otherwise `ERR_HOLD_ACTIVE`). The release record stamps `authorized_at` to the current clock, the order's cumulative `amount_paid_cents` is increased by the tendered amount, and the order becomes `RELEASED`. Release records can be listed for an order.

### 3.6. Fee Waivers and Disputes, with Segregation of Duties

A `Claimant` who believes a charge is wrong files a **fee waiver** against the tow order, supplying a `reason` (one of `WRONGFUL_TOW`, `HARDSHIP`, `LAW_ENFORCEMENT_ERROR`, or `BILLING_DISPUTE`) and a `requested_amount_cents` that must be greater than zero. On filing, the waiver begins in `REQUESTED` status and the server records `filed_by_user_id` as the filing claimant's `X-User-ID`. A waiver also carries the computed `approved_amount_cents` (set when approved), the `decided_by_user_id` of the operator who decided it, and a `status` running through `REQUESTED`, `UNDER_REVIEW`, `APPROVED`, `DENIED`, and `WITHDRAWN`, of which `APPROVED`, `DENIED`, and `WITHDRAWN` are terminal. Waivers can be listed for an order and filtered by `status`, and a single waiver can be fetched directly.

A `LotOperator` begins review of a waiver, moving it `REQUESTED → UNDER_REVIEW` (allowed only from `REQUESTED`, else `ERR_INVALID_STATE`). From `UNDER_REVIEW` an operator either approves or denies it, and both decisions are subject to **segregation of duties**: the deciding operator's `X-User-ID` must differ from the waiver's recorded `filed_by_user_id`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval moves the waiver `UNDER_REVIEW → APPROVED` (allowed only from `UNDER_REVIEW`, else `ERR_INVALID_STATE`); it sets `approved_amount_cents` to the capped credit described below, records `decided_by_user_id` as the approving operator's `X-User-ID`, adds that approved amount to the parent tow order's `waiver_credit_cents`, and recomputes the order's `net_due_cents`. Denial moves the waiver `UNDER_REVIEW → DENIED` (allowed only from `UNDER_REVIEW`, else `ERR_INVALID_STATE`); it records `decided_by_user_id` and makes no change to any balance. A `Claimant` may withdraw their own waiver, moving it `REQUESTED → WITHDRAWN` (allowed only from `REQUESTED`, else `ERR_INVALID_STATE`); only the filer may withdraw, so the acting `X-User-ID` must equal `filed_by_user_id`, and any other caller is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The credit actually granted on approval is governed by a tiered cap evaluated in a fixed order so that the value is well-defined even though the cap looks circular. First, the pre-waiver balance is read as the order's `balance_due_cents` (the pre-waiver breakdown from §3.5). Second, a cap percentage is selected from that pre-waiver balance: a balance below 50000 cents permits a cap of 100 percent (a full waiver); a balance from 50000 cents up to but not including 150000 cents permits a cap of 50 percent; and a balance of 150000 cents or more permits a cap of 25 percent. Third, the cap in cents is the pre-waiver balance multiplied by the cap percentage and divided by 100, with the result rounded **down** to a whole cent. Fourth, the `approved_amount_cents` is the smaller of the claimant's `requested_amount_cents` and that computed cap. The tier is always chosen from the pre-waiver balance, never from a post-waiver figure.

### 3.7. Provider Standing

A provider's reliability is summarized by two computed percentages, both reported when the provider is read. The first, `raw_standing_pct`, is the all-time instantaneous variant: it is the provider's `offers_accepted_count` divided by its `offers_received_count`, multiplied by 100 and rounded half-up to two decimal places; when `offers_received_count` is 0 the raw standing is defined as 100.00. The second, `effective_standing_pct`, is the trailing variant used as the eligibility signal: it considers only the most recent `trailing_window_size` rotation assignments offered to the provider, ordered by `offered_at` ascending and then by `created_at` ascending, and is computed as the count accepted within that window divided by the count offered within that window, multiplied by 100 and rounded half-up to two decimal places. If the provider is `SUSPENDED`, a suspension penalty of 20.0 percentage points is subtracted from the effective standing, with the result floored at 0.00. Both percentages are clamped to the range 0.00 through 100.00. The two variants diverge once a provider's history exceeds the trailing window or once the provider is suspended; with identical inputs inside the window and an active provider they agree. These standings are recomputed whenever a provider's counters change — that is, on accept, decline, and expire.

### 3.8. The Statutory Auction Path

Once a vehicle has sat long enough and its owner and lienholder have been duly noticed, it becomes eligible for sale. A `LotOperator` marks an order auction-eligible, moving it `STORED → AUCTION_ELIGIBLE`. This is allowed only from `STORED` (otherwise `ERR_INVALID_STATE`), requires `hold_status` to be `NONE` (otherwise `ERR_HOLD_ACTIVE`), and requires the order to have passed the statutory-eligibility gate, failing with `ERR_STATUTORY_PERIOD_NOT_ELAPSED` if it has not. On success it freezes accrual exactly as authorization does: it closes the current open `StorageLedgerEntry` with `segment_end` at the current clock and `kind` `FREEZE`, and sets `accrual_frozen_at`.

The statutory-eligibility gate is a boolean that is true only when **both** of two conditions hold. The first is that the holding period has elapsed: the days between `intake_at` and the current clock — counted by the ceiling-of-hours-over-24 day rule, with the boundary inclusive so that exactly the required number of days qualifies — is at least the lot's `statutory_hold_days`. The second is that the notice grace window has elapsed: there exists at least one notification on the order whose `status` is `DELIVERY_CONFIRMED` or `CERTIFIED_RETURNED` and whose days between `resolved_at` and the current clock (same ceiling day rule, same inclusive boundary) is at least the lot's `notice_grace_days`. Notifications that are merely `SENT`, and notifications that are `UNDELIVERABLE`, do not satisfy the second condition. Both conditions must be true at once for the order to be marked eligible.

An owner can still come forward before the gavel falls. A `LotOperator` reclaims an order, moving it `AUCTION_ELIGIBLE → STORED`; this is allowed only from `AUCTION_ELIGIBLE` (otherwise `ERR_INVALID_STATE`) and only while the order's `auction_id` is still null, meaning it has not yet been swept into an auction — reclaiming an already-swept order is rejected with `ERR_ALREADY_IN_AUCTION`. Reclaiming resumes accrual by opening a new `StorageLedgerEntry` with `kind` `RESUME` and `segment_start` at the current clock and clearing `accrual_frozen_at`, with the same compensating invariant that `accrued_days` continues from the frozen value and no day is double-counted.

### 3.9. Conducting an Auction and Distributing Proceeds

An auction is scheduled against a lot by an `AuctionOfficial` or a `LotOperator`, supplying the `lot_id`, a `window_start`, and a `window_end` that must be strictly after `window_start`. A new auction begins `SCHEDULED`. Two auctions on the same lot may not have overlapping windows: a scheduled window that overlaps an existing window on the same lot is rejected with `ERR_AUCTION_WINDOW_OVERLAP`. An auction carries the aggregate figures `gross_proceeds_cents` (the running sum of recorded sale prices, starting at 0), and the computed `distributed_cents`, `lien_payoff_cents`, and `surplus_to_owner_cents` described below. Its `status` runs through `SCHEDULED`, `OPEN`, `SETTLED`, and `CANCELLED`, of which `SETTLED` and `CANCELLED` are terminal. Auctions can be listed and filtered by `lot_id` and `status`, and the orders swept into one auction can be listed and filtered by `status`.

An `AuctionOfficial` opens a scheduled auction, moving it `SCHEDULED → OPEN`; opening is allowed only from `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and only once the current clock is at or after `window_start`, failing with `ERR_AUCTION_WINDOW_NOT_STARTED` before then. Opening enables sale recording. Eligible orders are brought into the auction by a sweep, performed by an `AuctionOfficial` or a `LotOperator` against the auction with the `tow_order_id` to bring in; a swept order must be in `AUCTION_ELIGIBLE` with `hold_status` `NONE`, otherwise the sweep is rejected with `ERR_INVALID_STATE` or `ERR_HOLD_ACTIVE` respectively, and on success the order's `auction_id` is linked to the auction.

Recording a sale is an `AuctionOfficial` action against the open auction, supplying the `tow_order_id` of the sold order and its `sale_price_cents`. The order must be in `AUCTION_ELIGIBLE` (otherwise `ERR_INVALID_STATE`), it must already be swept into this auction so that its `auction_id` equals this auction's id (otherwise `ERR_NOT_IN_AUCTION`), and its `hold_status` must be `NONE` (otherwise `ERR_HOLD_ACTIVE`). Recording a sale moves the order to the terminal `AUCTIONED` state, writes a `SETTLEMENT` `StorageLedgerEntry` finalizing the order's `accrued_storage_cents`, adds the `sale_price_cents` to the auction's `gross_proceeds_cents`, and re-runs the distribution waterfall on the auction.

The proceeds of each sold order are split through a deterministic waterfall in which the remainder cascades from one bucket to the next. For a sold order, the lot recovery is the smaller of the `sale_price_cents` and the sum of that order's `accrued_storage_cents` and the lot's `admin_fee_cents`. The lien payoff is then the smaller of whatever remains and the lot's `lien_processing_fee_cents` if the order has a lienholder, or zero if it does not. The surplus to the owner is whatever remains after those two buckets, floored at zero. For every sold order the three buckets exactly sum to the sale price — lot recovery plus lien payoff plus surplus equals `sale_price_cents` — and this conservation holds for each order. At the auction level, the aggregates are accumulated across its sold orders, processed in `created_at` ascending order: `gross_proceeds_cents` is the sum of every `sale_price_cents`, `distributed_cents` is the sum of every order's lot recovery, `lien_payoff_cents` is the sum of every order's lien payoff, and `surplus_to_owner_cents` is the sum of every order's surplus. Because the inputs are whole cents, the waterfall performs no rounding.

A recorded sale can be unwound. An `AuctionOfficial` voids a sale against the auction by naming the `tow_order_id`; this is a compensating action that returns the order to `AUCTION_ELIGIBLE`, removes the order's `SETTLEMENT` ledger entry, subtracts that order's sale price from the auction's `gross_proceeds_cents`, and recomputes the distribution waterfall so that conservation is restored. Settling an auction is an `AuctionOfficial` action that moves it `OPEN → SETTLED` (allowed only from `OPEN`, else `ERR_INVALID_STATE`) and finalizes the distribution waterfall. Cancelling a scheduled auction is an `AuctionOfficial` action that moves it `SCHEDULED → CANCELLED` (allowed only from `SCHEDULED`, else `ERR_INVALID_STATE`) and unlinks any swept orders by setting their `auction_id` back to null, leaving those orders in `AUCTION_ELIGIBLE`.

When an order is finally sold, the transition `AUCTION_ELIGIBLE → AUCTIONED` is the order's last move and is terminal; it is reachable only through the sale-recording path described above, where the order is in this auction and free of any hold.

### 3.10. How Validations Are Ordered

When more than one rule could reject a single request, the checks are applied in a fixed priority order, and the first rule that fails determines the error returned. The ordering is: first, that the `X-User-ID` and `X-User-Role` headers are present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); then, that the declared role is permitted for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`); then, that every resource referenced in the path or body exists, validated left-to-right through the path (`ERR_NOT_FOUND`); then, that the request body is well-formed — required fields present, enum values valid, amounts non-negative where required, and an auction's `window_end` strictly after its `window_start` (`ERR_INVALID_REQUEST`); then, that the stated foreign keys resolve and are mutually consistent (`ERR_REFERENCE_MISMATCH`); then, that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`).

Below those structural checks come the business rules, in this order: segregation of duties on a waiver decision, where the decider's `X-User-ID` must differ from `filed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); an active `POLICE_HOLD` or `EVIDENCE_HOLD` blocking release authorization, release recording, marking auction-eligible, and recording a sale (`ERR_HOLD_ACTIVE`); the combined statutory-hold-and-notice-grace gate on marking auction-eligible (`ERR_STATUTORY_PERIOD_NOT_ELAPSED`); the offer-expiry window on accepting a rotation offer (`ERR_OFFER_EXPIRED`); a pending `REQUESTED` or `UNDER_REVIEW` waiver blocking release authorization (`ERR_WAIVER_PENDING`); the requirement that `amount_paid_cents` cover `net_due_cents` before release authorization (`ERR_BALANCE_UNPAID`); the requirement that a lot be `OPEN` to accept new intake (`ERR_LOT_SUSPENDED`); the no-overlap rule on auction windows for the same lot (`ERR_AUCTION_WINDOW_OVERLAP`); and finally the optimistic-concurrency check that `expected_lot_version` equal the lot's current `version` on dispatch (`ERR_STALE_LOT_VERSION`). The practical consequence of this ordering is that a missing header is reported before a permission problem, a permission problem before a missing resource, a malformed body before a state problem, and a state problem before any of the domain-specific business rules.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code; operations that modify an existing resource, including state-transition actions, return a `200 OK` status code. Request and response bodies are not enumerated here — refer to the workflow narratives in §3 to reconstruct each operation's inputs, outputs, and side effects.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/impound-lots` | Create an impound lot | LotOperator |
| GET | `/impound-lots/{id}` | Get an impound lot | LotOperator, PoliceOfficer, TowProvider, Claimant, AuctionOfficial |
| POST | `/impound-lots/{id}/suspend` | Suspend a lot (blocks new intake) | LotOperator |
| POST | `/impound-lots/{id}/dispatch-rotation` | Dispatch the next rotation call | LotOperator |
| POST | `/tow-providers` | Register a tow provider on the rotation list | LotOperator |
| GET | `/tow-providers/{id}` | Get a tow provider | LotOperator, TowProvider, AuctionOfficial |
| POST | `/tow-providers/{id}/suspend` | Suspend a provider | LotOperator |
| POST | `/tow-providers/{id}/reinstate` | Reinstate a suspended provider | LotOperator |
| POST | `/lienholders` | Create a lienholder record | LotOperator |
| GET | `/lienholders/{id}` | Get a lienholder | LotOperator, Claimant |
| GET | `/rotation-assignments/{id}` | Get a rotation assignment | LotOperator, TowProvider |
| GET | `/rotation-assignments` | List/filter rotation assignments | LotOperator, TowProvider |
| POST | `/rotation-assignments/{id}/accept` | Provider accepts a rotation offer | TowProvider |
| POST | `/rotation-assignments/{id}/decline` | Provider declines; cascade re-offer | TowProvider |
| POST | `/rotation-assignments/{id}/expire` | Expire an offer past its TTL; cascade re-offer | LotOperator |
| POST | `/rotation-assignments/{id}/cancel` | Cancel an offer without re-offering | LotOperator |
| POST | `/tow-orders` | Create a tow intake order | LotOperator, PoliceOfficer |
| GET | `/tow-orders/{id}` | Get a tow order | LotOperator, PoliceOfficer, Claimant, AuctionOfficial |
| GET | `/tow-orders` | List/filter tow orders | LotOperator, PoliceOfficer, AuctionOfficial, Claimant |
| POST | `/tow-orders/{id}/store` | Move order to STORED; open accrual ledger | LotOperator |
| POST | `/tow-orders/{id}/authorize-release` | Authorize release once fees satisfied and no hold | LotOperator |
| POST | `/tow-orders/{id}/lapse-authorization` | Lapse a release authorization; resume accrual | LotOperator |
| POST | `/tow-orders/{id}/mark-auction-eligible` | Mark order auction-eligible; freeze accrual | LotOperator |
| POST | `/tow-orders/{id}/reclaim` | Revert auction-eligible order back to stored | LotOperator |
| POST | `/tow-orders/{id}/void` | Void a wrongful/erroneous tow | PoliceOfficer |
| POST | `/tow-orders/{id}/place-hold` | Place a police/evidence hold | PoliceOfficer |
| POST | `/tow-orders/{id}/lift-hold` | Lift the active hold | PoliceOfficer |
| GET | `/tow-orders/{id}/ledger-entries` | List storage ledger entries | LotOperator, Claimant, AuctionOfficial |
| POST | `/tow-orders/{id}/notifications` | Create a draft notification | LotOperator |
| GET | `/tow-orders/{id}/notifications` | List notifications | LotOperator, Claimant |
| GET | `/tow-orders/{id}/notifications/{nid}` | Get a single notification | LotOperator, Claimant |
| POST | `/tow-orders/{id}/notifications/{nid}/send` | Send a notification | LotOperator |
| POST | `/tow-orders/{id}/notifications/{nid}/confirm-delivery` | Confirm delivery; start grace clock | LotOperator |
| POST | `/tow-orders/{id}/notifications/{nid}/mark-returned` | Mark certified mail returned | LotOperator |
| POST | `/tow-orders/{id}/notifications/{nid}/mark-undeliverable` | Mark notice undeliverable | LotOperator |
| POST | `/tow-orders/{id}/inventory-items` | Document a photo/inventory item | LotOperator |
| GET | `/tow-orders/{id}/inventory-items` | List inventory items | LotOperator, Claimant |
| POST | `/tow-orders/{id}/fee-waivers` | File a fee waiver / dispute | Claimant |
| GET | `/tow-orders/{id}/fee-waivers` | List fee waivers | LotOperator, Claimant |
| GET | `/tow-orders/{id}/fee-waivers/{wid}` | Get a fee waiver | LotOperator, Claimant |
| POST | `/tow-orders/{id}/fee-waivers/{wid}/start-review` | Begin review of a fee waiver | LotOperator |
| POST | `/tow-orders/{id}/fee-waivers/{wid}/approve` | Approve a fee waiver; apply tiered credit | LotOperator |
| POST | `/tow-orders/{id}/fee-waivers/{wid}/deny` | Deny a fee waiver | LotOperator |
| POST | `/tow-orders/{id}/fee-waivers/{wid}/withdraw` | Withdraw own waiver | Claimant |
| POST | `/tow-orders/{id}/release-records` | Record physical release | LotOperator |
| GET | `/tow-orders/{id}/release-records` | List release records | LotOperator, Claimant |
| POST | `/tow-orders/{id}/payments` | Record a payment toward the order balance | LotOperator, Claimant |
| POST | `/auctions` | Schedule an auction window for a lot | AuctionOfficial, LotOperator |
| GET | `/auctions/{id}` | Get an auction | AuctionOfficial, LotOperator |
| GET | `/auctions` | List/filter auctions | AuctionOfficial, LotOperator |
| GET | `/auctions/{id}/tow-orders` | List orders swept into an auction | AuctionOfficial, LotOperator |
| POST | `/auctions/{id}/open` | Open a scheduled auction | AuctionOfficial |
| POST | `/auctions/{id}/sweep` | Sweep an eligible order into this auction | AuctionOfficial, LotOperator |
| POST | `/auctions/{id}/record-sale` | Record a sale; cascade proceeds distribution | AuctionOfficial |
| POST | `/auctions/{id}/void-sale` | Void a recorded sale; reverse distribution | AuctionOfficial |
| POST | `/auctions/{id}/settle` | Settle an open auction | AuctionOfficial |
| POST | `/auctions/{id}/cancel` | Cancel a scheduled auction; unlink swept orders | AuctionOfficial |
| POST | `/_clock/set` | Set the server's current UTC clock | LotOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_REFERENCE_MISMATCH` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVENTORY_REQUIRED` | 409 Conflict |
| `ERR_HOLD_ACTIVE` | 409 Conflict |
| `ERR_NO_HOLD` | 409 Conflict |
| `ERR_WAIVER_PENDING` | 409 Conflict |
| `ERR_BALANCE_UNPAID` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_STATUTORY_PERIOD_NOT_ELAPSED` | 409 Conflict |
| `ERR_NO_LIENHOLDER` | 409 Conflict |
| `ERR_METHOD_NOT_CERTIFIED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_OFFER_NOT_EXPIRED` | 409 Conflict |
| `ERR_PROVIDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_ELIGIBLE_PROVIDER` | 409 Conflict |
| `ERR_LOT_SUSPENDED` | 409 Conflict |
| `ERR_AUCTION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AUCTION_WINDOW_NOT_STARTED` | 409 Conflict |
| `ERR_ALREADY_IN_AUCTION` | 409 Conflict |
| `ERR_NOT_IN_AUCTION` | 409 Conflict |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
