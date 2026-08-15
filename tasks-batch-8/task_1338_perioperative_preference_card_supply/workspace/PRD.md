# Perioperative Preference Card Supply API — Product Requirements Document

## 1. Introduction

Every operating room runs on surgeon preference cards: the living documents that tell the case-cart team exactly which supplies a given surgeon wants for a given procedure, in what quantities, and with what handling. When cards drift out of date, the consequences are concrete and expensive — wrong items pulled, opened-but-unused disposables discarded, consignment implants billed incorrectly, and standardization initiatives that stall because nobody can prove which card version actually performed well. This document specifies the Perioperative Preference Card Supply API, a system that manages the full loop from card authoring and version control through case-cart picking, substitution under shortage, intra-operative usage capture, post-case accuracy audits, and the value-analysis pipeline that governs new product introduction.

The API serves six operational roles across the OR supply chain: analysts who own cards and case scheduling, cart technicians who build and dispatch case carts, circulating nurses who record what was actually used, materials managers who steward stock and consignment billing, value-analysis officers who gate new products, and surgeons themselves, who request new items and may dispute audits of their own cards. Because a single case completion simultaneously settles usage costs, waste charges, consignment billing, and card accuracy scoring, the system places heavy emphasis on atomic multi-entity side effects, optimistic concurrency on versioned cards and pinned cases, and a strictly ordered validation pipeline. All resources are exposed under the `/perioperative` mount as flat, peer collections; parent-child relationships are expressed through references on the resources themselves rather than through nested URLs.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply uniformly to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational role. A request missing either header, or carrying a role name the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once authenticated, the caller's role is checked against the endpoint's authorization policy; a caller whose role is not permitted — or who fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes six operational roles, spelled exactly as follows: `Surgeon`, `SupplyChainAnalyst`, `CartTechnician`, `CirculatingNurse`, `ValueAnalysisOfficer`, and `MaterialsManager`. A seventh designation, `Any`, denotes that every authenticated role may call the read endpoints: all GET operations are authorized for `Any`.

Role identity is bound to `X-User-ID` differently per role. When `X-User-Role` is `Surgeon`, `X-User-ID` is the `id` of the acting `Surgeon` entity; ownership checks on any resource that references a `Surgeon` compare the resource's foreign-key field to `X-User-ID` — concretely, a product request records the acting surgeon's `id` as its `surgeon_id`, and a card-audit dispute is only permitted when the audited card's owning surgeon matches `X-User-ID`. When `X-User-Role` is `SupplyChainAnalyst`, `CartTechnician`, `CirculatingNurse`, `ValueAnalysisOfficer`, `MaterialsManager`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `reviewing_officer_id` on a `ProductRequest` or as entries in `endorser_ids` — but it does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Both are validated as part of request-shape checking.

Unless an endpoint states otherwise, list responses are sorted by `created_at` in ascending order. Two collections break from this convention: preference card lines and pick list lines are sorted by `pick_sequence` ascending, with ties broken by `created_at` ascending, so that pickers always see lines in tray-layout order. The `meta` envelope of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — surgeons, supply items, preference cards and their lines, surgical cases, pick lists and their lines, usage records, card accuracy audits, product requests, consignment counts, and consignment charges — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, including system-driven state transitions, derived-field recomputations, and cascade effects. It is the basis of optimistic concurrency control (§2.6).

Because resource paths in this API are flat (a single `{id}` segment under each collection), existence validation of the path identifier is straightforward: the path `id` is validated first, before any identifier referenced inside the request body. A path or body identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404).

### 2.5. Money, Percentages, and Rounding Discipline

All monetary values in the system are represented as integer cents — never fractional currency units. This applies to stored fields such as `unit_cost_cents`, `estimated_cost_cents`, `standard_cost_cents`, `actual_cost_cents`, `waste_cost_cents`, `consignment_budget_cents`, `estimated_unit_cost_cents`, `variance_value_cents`, `waste_charge_cents`, and `amount_cents`, and to all arithmetic over them. Integer-cent aggregates require no rounding.

All percentage fields — every field whose name ends in `_pct`, such as `line_match_pct`, `spend_match_pct`, `waste_pct`, and `rolling_line_match_pct` — are numbers carried to exactly 2 decimal places, rounded half up (for example, a raw value of 66.665 becomes 66.67). Where a threshold compares against a percentage, the comparison is applied to the already-rounded value, not the raw quotient.

### 2.6. Card Versioning, Case Pinning, and Optimistic Concurrency Control

Preference cards carry two distinct version concepts that implementers must not conflate. The business version, `version_number`, identifies generations of a card for a given surgeon-and-procedure pair: the first card created for a pair receives `version_number` 1, and each subsequently created card for the same pair receives one more than the highest existing `version_number` for that pair. The system `version` (§2.4) is the optimistic-concurrency token and increments on every mutation — adding or deleting a line, publishing, retiring, or being superseded all advance it.

Two write operations are guarded by optimistic concurrency control, and these are the only two endpoints that accept a version field:

1. Publishing a card requires the request to carry `expected_card_version`, holding the card `version` the client last observed. If it does not equal the card's current `version` — for example because another writer added a line in the meantime, which itself increments `version` — the publish is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the card and retry against the current version.
2. Re-pinning a case to a different card requires `expected_case_version`, holding the case `version` the client last observed. A mismatch with the case's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. The OCC check is evaluated after the target's state preconditions and before any business rules (§2.7).

### 2.7. Validation Order and Request Atomicity

Every mutation endpoint runs its validations in a fixed, global order, and all validations for an endpoint complete before any mutation is applied — a failed request applies zero side effects, no matter how far into the pipeline it traveled. The priority order is:

1. **Authentication context**: `X-User-ID` and `X-User-Role` present and the role recognized — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization**: the caller's role is permitted on the endpoint, including entity-backed ownership checks — `ERR_FORBIDDEN_FOR_ROLE`.
3. **Request body shape**: required fields present, enum values valid, integer ranges respected (`quantity` at least 1, `qty_used` no less than 0, `expected_duration_min` at least 1), and `rationale` length at least 10 characters — `ERR_INVALID_REQUEST` or `ERR_INVALID_QUANTITY`.
4. **Existence**: path identifiers resolve, left to right, then body-referenced identifiers (`surgeon_id`, `card_id`, `supply_item_id`, `substitute_supply_item_id`, entry line ids, `replaces_item_id`) — `ERR_NOT_FOUND`.
5. **Target state**: the resource's current state permits the operation, per the state machines in §3 — `ERR_CARD_NOT_DRAFT`, `ERR_CASE_NOT_SCHEDULED`, `ERR_CASE_NOT_CANCELLABLE`, `ERR_CASE_NOT_COMPLETABLE`, `ERR_PICK_LIST_INVALID_STATE`, `ERR_LINE_NOT_PENDING`, `ERR_LINE_NOT_SHORT`, `ERR_AUDIT_NOT_ACTIONABLE`, `ERR_AUDIT_NOT_DISPUTED`, `ERR_REQUEST_NOT_UNDER_REVIEW`, `ERR_CHARGE_INVALID_STATE`, `ERR_COUNT_NOT_RECORDED`, or `ERR_PICK_LIST_EXISTS`, as applicable.
6. **Optimistic concurrency**: on the two OCC-guarded writes only, the expected version matches the current version — `ERR_STALE_VERSION`.
7. **Clinical safety business rules**: substitution group compatibility, same-item substitution, usage within opened quantity, substitute item active — `ERR_SUBSTITUTE_GROUP_MISMATCH`, `ERR_INVALID_REQUEST`, `ERR_USAGE_EXCEEDS_OPENED`, `ERR_ITEM_NOT_ACTIVE`.
8. **Cross-entity referential coherence**: card active at case create/release/repin, case surgeon matching card surgeon, surgeon or requester active, entry lines belonging to the case's pick list, counted item being consignment, card-line item active, card not in use for retire — `ERR_PINNED_CARD_NOT_ACTIVE`, `ERR_CARD_SURGEON_MISMATCH`, `ERR_SURGEON_INACTIVE`, `ERR_REQUESTER_INACTIVE`, `ERR_LINE_CASE_MISMATCH`, `ERR_NOT_CONSIGNMENT_ITEM`, `ERR_ITEM_NOT_ACTIVE`, `ERR_CARD_IN_USE`. Within this tier on case creation, the checks evaluate in this order: the pinned card is `ACTIVE` first, then surgeon match, then the surgeon is `ACTIVE`.
9. **Scheduling conflicts**: room overlap is evaluated first — `ERR_ROOM_DOUBLE_BOOKED` — then the surgeon turnover-buffer gap — `ERR_SURGEON_SCHEDULE_CONFLICT`.
10. **Structural constraints**: duplicate card line, empty-card publish, duplicate endorsement, quorum, segregation of duties, duplicate SKU — `ERR_DUPLICATE_CARD_LINE`, `ERR_CARD_EMPTY`, `ERR_DUPLICATE_ENDORSEMENT`, `ERR_QUORUM_NOT_MET`, `ERR_SOD_REVIEWER_CANNOT_APPROVE` (HTTP 403), or `ERR_INVALID_REQUEST` for a duplicate SKU.
11. **Fiscal guards**: substitution price threshold and consignment budget — `ERR_SUBSTITUTE_PRICE_THRESHOLD` or `ERR_CONSIGNMENT_BUDGET_EXCEEDED` (both HTTP 402).

### 2.8. The Sterile-Core Stock Ledger

Each supply item's `on_hand_quantity` is a ledger of sterile-core stock. It is initialized from `initial_on_hand` at item creation (zero when that field is omitted) and is thereafter mutated by exactly six events, and no others: signed stock adjustments posted by a `MaterialsManager`; picks, which decrement it by the requested quantity; substitutions, which decrement the substitute item; cart returns, which increment it by the returned-unopened quantity; case cancellation, which restocks every picked quantity; and verified consignment counts, which apply the recorded variance. Every adjustment is applied atomically with the operation that caused it, and the ledger never silently drifts: an operation that cannot apply its full stock effect is rejected in its entirety.

### 2.9. Scheduling Time and Request-Supplied Temporal Inputs

The system maintains no logical clock and exposes no time-travel or clock-advance endpoint. All temporal inputs — `scheduled_start` and `expected_duration_min` on case scheduling — are explicit request fields, and every temporal comparison the system performs (room overlap, surgeon turnover buffer) is computed between request-supplied values and the stored scheduling fields of existing cases. A case occupies the half-open interval beginning at its `scheduled_start` and extending for `expected_duration_min` minutes, inclusive of the start instant and exclusive of the end instant.

## 3. Business Logic & Workflows

### 3.1. Surgeons and the Supply Item Catalog

A `SupplyChainAnalyst` onboards the surgical roster by registering each surgeon with a `full_name` and a free-form `specialty` label (for example, ORTHO or CARD). Newly registered surgeons carry `status` `ACTIVE`. When a surgeon leaves the roster, the analyst deactivates them, moving `status` from `ACTIVE` to `INACTIVE`; deactivating an already-`INACTIVE` surgeon is a state-precondition violation and is rejected with `ERR_INVALID_STATE` (HTTP 409). Deactivation applies no cascade — existing cards, cases, and requests are untouched — but downstream guards immediately begin rejecting new work for that surgeon: creating a card, publishing a card, scheduling a case, or submitting a product request all fail with `ERR_SURGEON_INACTIVE`, and approval of that surgeon's pending product request fails with `ERR_REQUESTER_INACTIVE`.

The supply catalog is likewise owned by the `SupplyChainAnalyst`. Creating a supply item requires a `sku` (unique across all items — a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400), a display `name`, and a `unit_cost_cents` of at least 1. The optional `substitute_group` labels interchangeability: two items are valid substitutes for one another if and only if both carry an equal, non-null `substitute_group`; a null group — the default — means the item has no valid substitutes. The `consignment_flag` (default false) marks vendor-owned stock that is billed when opened. At creation the item's `on_hand_quantity` is seeded from the optional `initial_on_hand`, defaulting to zero, and `status` starts as `ACTIVE`. The catalog list supports filtering by `substitute_group`, `consignment_flag`, and `status`.

Day-to-day stock stewardship falls to the `MaterialsManager`, who posts signed stock adjustments carrying a `delta_qty` and a `reason`. The adjustment is added to `on_hand_quantity`; any adjustment whose result would drop the balance below zero is rejected with `ERR_INVALID_QUANTITY`. An item's lifecycle ends in `DISCONTINUED`, reached only as a system cascade when a product request naming it as `replaces_item_id` is approved (§3.7); from that moment, new card lines naming the item are rejected with `ERR_ITEM_NOT_ACTIVE`, and publishing a draft card that still contains it is likewise rejected.

### 3.2. Authoring and Publishing Preference Cards

Preference cards are the heart of the system. An analyst creates a card by naming its owning `surgeon_id` and a `procedure_name` — a label such as TOTAL_KNEE_ARTHROPLASTY that groups comparable cards for the standardization initiative. The surgeon must be `ACTIVE` (`ERR_SURGEON_INACTIVE` otherwise). The new card arrives in `DRAFT` status with `version_number` set to 1 when no card exists for that surgeon-and-procedure pair, or one more than the highest existing `version_number` for the pair otherwise. Cards may be listed with `surgeon_id`, `procedure_name`, and `status` filters.

While the card is `DRAFT`, the analyst builds it out line by line. Each line references its `card_id` — the card must still be `DRAFT`, or the add is rejected with `ERR_CARD_NOT_DRAFT` — and a `supply_item_id` naming an `ACTIVE` item (`ERR_ITEM_NOT_ACTIVE` otherwise). Every line declares a `quantity` of at least 1 and a `designation` of exactly `OPEN` or `HOLD`: `OPEN` items are opened onto the sterile field at case start, while `HOLD` items are held back and opened only on request, a distinction that later drives waste charging. An optional `pick_sequence` controls tray order and defaults to the line's 1-based creation-order index when omitted; an optional `notes` field carries free-form picker guidance. A card may not contain two lines for the same item — a duplicate (`card_id`, `supply_item_id`) pair is rejected with `ERR_DUPLICATE_CARD_LINE`. Removing a line from a `DRAFT` card is permitted under the same `ERR_CARD_NOT_DRAFT` guard and returns no content. Card lines are listed in `pick_sequence` order and may be filtered by `card_id` and `supply_item_id`.

The card's `estimated_cost_cents` is a live computed field: after every line addition or deletion it is recomputed in full as the sum, over the card's current lines regardless of designation, of each line's `quantity` multiplied by its item's `unit_cost_cents`. Every such line mutation also increments the card's `version` by one — which is precisely why publishing is OCC-guarded (§2.6).

Publishing is the act that makes a `DRAFT` card operative, moving it `DRAFT → ACTIVE`. The analyst's publish request must carry `expected_card_version` matching the card's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Beyond the OCC check, publish enforces, in the global validation order: the card is `DRAFT` (`ERR_CARD_NOT_DRAFT`), it has at least one line (`ERR_CARD_EMPTY`), every line's item is `ACTIVE` (`ERR_ITEM_NOT_ACTIVE`), and its surgeon is `ACTIVE` (`ERR_SURGEON_INACTIVE`). On success the published card's `version` increments by one, and any other `ACTIVE` card for the same surgeon-and-procedure pair transitions `ACTIVE → SUPERSEDED` with its own `version` incremented by one. Cases already `SCHEDULED` against the superseded card keep their pin untouched — but their pick-list release will now fail with `ERR_PINNED_CARD_NOT_ACTIVE` until they are re-pinned (§3.3), which is the intended forcing function that moves the schedule onto current practice.

A card may be retired from either `DRAFT` or `ACTIVE`, ending in `RETIRED` with `version` incremented by one. Retiring an `ACTIVE` card is blocked while any case pinned to it is in `SCHEDULED`, `PICKING_RELEASED`, or `IN_PROGRESS` — such an attempt is rejected with `ERR_CARD_IN_USE`. Retiring a `DRAFT` card carries no preconditions.

### 3.3. Scheduling Cases: Pinning, Conflicts, and Changes of Plan

Scheduling a surgical case pins it, once and deliberately, to a specific card generation. The analyst supplies the performing `surgeon_id`, the `card_id` of the preference card to pin, the `scheduled_start` as an ISO 8601 UTC instant, an `expected_duration_min` of at least 1, the `room` identifier (for example OR-1), and optionally a `consignment_budget_cents` — a per-case cap on total consignment charges that must be at least 1 when present and whose absence (null) leaves the case uncapped. Cross-entity checks then run in this order: the pinned card must be `ACTIVE` (`ERR_PINNED_CARD_NOT_ACTIVE`), the case's surgeon must equal the pinned card's surgeon (`ERR_CARD_SURGEON_MISMATCH`), and the surgeon must be `ACTIVE` (`ERR_SURGEON_INACTIVE`).

Scheduling conflicts are evaluated next, room first, then surgeon. A room conflict exists when the new case's half-open interval — from `scheduled_start` up to but not including `scheduled_start` plus `expected_duration_min` minutes — intersects the interval of any non-`CANCELLED` case in the same `room`; intervals that merely touch at an endpoint do not conflict. A violation is rejected with `ERR_ROOM_DOUBLE_BOOKED`. The surgeon then receives a mandatory 30-minute turnover buffer: if any non-`CANCELLED` case for the same surgeon ends less than 30 minutes before the new case starts, or begins less than 30 minutes after the new case ends, scheduling is rejected with `ERR_SURGEON_SCHEDULE_CONFLICT`; a gap of exactly 30 minutes is permitted.

On creation the case lands in `SCHEDULED` with `pinned_card_version_number` captured from the card's `version_number` and `procedure_name` copied from the card. The pin is frozen: publishing a newer card generation never advances an existing case's pin. Cases are listed in creation order with `surgeon_id`, `card_id`, `status`, and `room` filters, and the computed cost fields `standard_cost_cents`, `actual_cost_cents`, and `waste_cost_cents` remain null until the workflows that produce them (§3.4, §3.5).

When a newer card generation publishes and a `SCHEDULED` case is left pointing at a superseded version, the analyst re-pins the case. Re-pinning is only possible while the case is `SCHEDULED` (`ERR_CASE_NOT_SCHEDULED` otherwise) and is OCC-guarded: the request carries the target `card_id` plus `expected_case_version` equal to the case's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). The new card must be `ACTIVE` (`ERR_PINNED_CARD_NOT_ACTIVE`), belong to the same surgeon as the case (`ERR_CARD_SURGEON_MISMATCH`), and share the case's `procedure_name`. A successful re-pin updates the pinned card, re-captures `pinned_card_version_number`, refreshes `procedure_name`, and increments the case's `version` by one.

Cancellation is a pre-dispatch escape hatch. A case may be cancelled from `SCHEDULED` or from `PICKING_RELEASED`; if a pick list already exists, it must still be in `GENERATED`, `IN_PICKING`, or `PICKING_EXCEPTION`. Any other constellation — a list already `STAGED`, `DISPATCHED`, `RETURNED`, or `CLOSED`, or a case already `IN_PROGRESS`, `COMPLETED`, or `CANCELLED` — is rejected with `ERR_CASE_NOT_CANCELLABLE`. Cancellation is hygienic about stock: every pick line's `qty_picked` is restocked to its item's `on_hand_quantity`, the pick list transitions to `CANCELLED`, and the case transitions to `CANCELLED`.

### 3.4. From Release to Dispatch: Building the Case Cart

Releasing the pick list converts a scheduled case into physical work. A `SupplyChainAnalyst` may release only a `SCHEDULED` case (`ERR_CASE_NOT_SCHEDULED` otherwise) that does not yet have a pick list — exactly one pick list ever exists per case, and a second release is rejected with `ERR_PICK_LIST_EXISTS` — and whose pinned card is still `ACTIVE` (`ERR_PINNED_CARD_NOT_ACTIVE`). Release creates the pick list in `GENERATED` status, stamped with the case's `case_id` and carrying `card_id` and `card_version_number` copied from the case's pin, along with one pick list line per line of the pinned card version. Each pick line snapshots the card line's `designation`, its planned quantity as `qty_requested`, the item's release-time `unit_cost_cents`, and the `pick_sequence` for stable ordering, and begins in `PENDING` with `qty_picked` and `qty_returned_unopened` at zero. In the same atomic step the case's `standard_cost_cents` is computed — the as-planned cost, being the sum over the snapshot lines of `qty_requested` multiplied by the snapshot `unit_cost_cents` — and the case moves `SCHEDULED → PICKING_RELEASED`. The standard cost prices the pinned card exactly as written and never changes after release. Pick lists may be listed with `case_id`, `card_id`, and `status` filters.

A `CartTechnician` begins work by transitioning the list `GENERATED → IN_PICKING`; beginning from any other state is rejected with `ERR_PICK_LIST_INVALID_STATE`. The technician then resolves each `PENDING` line in one of two ways.

Picking a line pulls the full requested quantity of the planned item: the line must be `PENDING` (`ERR_LINE_NOT_PENDING`), its parent list must be `IN_PICKING` or `PICKING_EXCEPTION` (`ERR_PICK_LIST_INVALID_STATE`), and the item's `on_hand_quantity` must be at least `qty_requested` — equality is sufficient — with shortfalls rejected as `ERR_INSUFFICIENT_STOCK`. A successful pick sets `qty_picked` equal to `qty_requested`, decrements the item's `on_hand_quantity` by `qty_requested`, and moves the line `PENDING → PICKED`. When this pick resolves the final line still sitting in `PENDING` or `SHORT`, the list auto-transitions `IN_PICKING → STAGED`.

When the shelf comes up empty, the technician instead marks the line short, recording a free-form `reason_code` that is stored on the line as `short_reason_code`, under the same `PENDING`-line and list-state guards (`ERR_LINE_NOT_PENDING`, `ERR_PICK_LIST_INVALID_STATE`). Marking short moves the line `PENDING → SHORT` and pushes the list `IN_PICKING → PICKING_EXCEPTION` — a no-op if the list is already in exception. Each entry of the list into `PICKING_EXCEPTION` increments the case's `pick_exception_count` by exactly one; marking a second line short while the list is already in exception does not increment it again.

A `SHORT` line is resolved by substitution. The technician names a `substitute_supply_item_id`, which must exist (`ERR_NOT_FOUND`), must differ from the planned item (`ERR_INVALID_REQUEST`), and must be `ACTIVE` (`ERR_ITEM_NOT_ACTIVE`). The substitute's `substitute_group` must be non-null and equal to the planned item's `substitute_group` (`ERR_SUBSTITUTE_GROUP_MISMATCH`), and its `on_hand_quantity` must cover `qty_requested` with equality sufficient (`ERR_INSUFFICIENT_STOCK`). Price discipline applies: the substitute's `unit_cost_cents` may not exceed 1.25 times the planned line's current snapshot `unit_cost_cents` — a substitute costing exactly 1.25 times as much is allowed — unless the request sets `override_price_threshold` to true; an unoverridden breach is rejected with `ERR_SUBSTITUTE_PRICE_THRESHOLD` (HTTP 402). Substitution sets `qty_picked` to `qty_requested` drawn from the substitute's stock, decrements the substitute's `on_hand_quantity` accordingly, re-snapshots the line's `unit_cost_cents` from the substitute item, records `substituted_item_id`, and moves the line `SHORT → SUBSTITUTED`. When the substitution clears the last `SHORT` line, the list returns `PICKING_EXCEPTION → IN_PICKING`; if at that point no `PENDING` lines remain either, the list continues automatically into `STAGED`. Pick list lines may be listed with `pick_list_id`, `supply_item_id`, `substituted_item_id`, and `status` filters, always in `pick_sequence` order.

Dispatch is the handoff to the OR. A `CartTechnician` dispatches only a `STAGED` list (`ERR_PICK_LIST_INVALID_STATE`), moving it `STAGED → DISPATCHED`; in the same moment the case transitions `PICKING_RELEASED → IN_PROGRESS`.

### 3.5. Cart Return, Usage Capture, and Case Completion

After the case, the cart comes back. The technician returns a `DISPATCHED` list (`ERR_PICK_LIST_INVALID_STATE`) by supplying `return_entries`, one per line with unopened stock coming back. Every entry's `pick_list_line_id` must belong to this list (`ERR_LINE_CASE_MISMATCH`), and each `qty_returned_unopened` must lie between zero and that line's `qty_picked`, both bounds inclusive (`ERR_INVALID_QUANTITY`). Each accepted entry records `qty_returned_unopened` on the line and adds that quantity back to the item's `on_hand_quantity` — to the substitute item's stock when the line was `SUBSTITUTED`. The list then moves `DISPATCHED → RETURNED`.

Completion is the system's heaviest transaction and belongs to the `CirculatingNurse`, who records what the case actually consumed via `usage_entries`. The case must be `IN_PROGRESS` with its pick list `RETURNED` (`ERR_CASE_NOT_COMPLETABLE` otherwise). Each entry's `qty_used` must be no less than zero (`ERR_INVALID_QUANTITY`); each entry's `pick_list_line_id` must exist (`ERR_NOT_FOUND`); no entry may claim more than its line actually left the shelf with — `qty_used` may not exceed the line's `qty_picked` minus its `qty_returned_unopened` (`ERR_USAGE_EXCEEDS_OPENED`, HTTP 422); and every entry must reference a line of this case's own pick list (`ERR_LINE_CASE_MISMATCH`). Only when every check passes does the atomic commit begin.

Completion creates one `UsageRecord` per `PICKED` or `SUBSTITUTED` pick line, each stamped with `case_id`, `pick_list_line_id`, and the `supply_item_id` actually consumed — the substitute item where the line was substituted. The record's `qty_opened` is the line's `qty_picked` minus its `qty_returned_unopened`; `qty_used` comes from the matching usage entry, or zero when the line has no entry; `qty_wasted` is `qty_opened` minus `qty_used`; and `unit_cost_cents` is snapshot from the pick line. Usage records may be listed with `case_id`, `pick_list_line_id`, and `supply_item_id` filters.

Each usage record then carries a `waste_charge_cents`, computed per line. When `qty_wasted` is zero the charge is zero. Otherwise the charge is `qty_wasted` multiplied by `unit_cost_cents` multiplied by a designation-driven multiplier: 1.0 when the item's `consignment_flag` is true (consignment waste is billed at cost), 1.5 when the line's snapshot `designation` is `HOLD` (hold items opened unnecessarily carry a penalty), and 1.0 for `OPEN` lines. Each line's charge is rounded half up to whole cents individually, and only then are the per-line values summed — summing unrounded line values and rounding once is forbidden.

From these records the case settles its costs. `waste_cost_cents` is the sum of the per-line waste charges. `actual_cost_cents` — the as-used variant of case costing — is the sum over usage records of `qty_used` times `unit_cost_cents`, plus the waste total; because it prices the substitute item rather than the planned one, excludes returned-unopened quantities, and adds waste charges, it diverges from `standard_cost_cents` whenever reality deviates from plan.

Consignment billing attaches at the same moment: for every usage record whose item has `consignment_flag` true and `qty_opened` greater than zero, the system creates a `ConsignmentCharge` in `PENDING` status, stamped with `case_id`, `usage_record_id`, and `supply_item_id`. Consignment bills on open, not on use, so `qty_billed` equals the usage record's `qty_opened`, and `amount_cents` is `qty_billed` times the record's `unit_cost_cents`. Before any of this commits, the budget guard runs: when the case carries a `consignment_budget_cents`, the sum of the resulting charges' `amount_cents` must not exceed it, or the entire completion is rejected with `ERR_CONSIGNMENT_BUDGET_EXCEEDED` (HTTP 402).

Finally, completion generates the `CardAccuracyAudit` in `GENERATED` status, stamped with `case_id`, `card_id`, and the `card_version_number` under audit. Two scoring variants grade the pinned card. The nursing-compliance variant counts lines: `matched_line_count` is the number of pinned card lines whose pick line was not substituted and whose `qty_used` equals `qty_requested`; `total_line_count` is the number of lines on the pinned card version at release; and `line_match_pct` is `matched_line_count` divided by `total_line_count`, times 100, rounded half up to 2 decimal places. The standardization variant weighs spend: `spend_match_pct` is one minus the absolute difference between `actual_cost_cents` and `standard_cost_cents` divided by `standard_cost_cents`, floored at zero, times 100, rounded half up to 2 decimal places — with the degenerate cases pinned: 100.0 when standard and actual are both zero, and 0.0 when standard is zero but actual is positive. Waste is graded by `waste_pct`, the case's `waste_cost_cents` divided by `standard_cost_cents` times 100, rounded half up to 2 decimal places, and defined as 0.0 when `standard_cost_cents` is zero. When the rounded `waste_pct` reaches 20.0 the audit's `waste_flag` is set true — exactly 20.0 flags; 19.98 does not — because the comparison applies to the rounded value.

The audit's arrival updates the card itself: the card's `flagged_audit_count` increments by one when the new audit's `waste_flag` is true, and its `rolling_line_match_pct` is recomputed as the mean of `line_match_pct` across all audits of the card, rounded half up to 2 decimal places — remaining null until the card's first audit exists. The case moves `IN_PROGRESS → COMPLETED`, and its pick list moves `RETURNED → CLOSED`.

### 3.6. Card Accuracy Audits and Surgeon Disputes

Audits are listed in creation order with `case_id`, `card_id`, and `status` filters. Disposition is shared between the analyst and the surgeon, with a deliberately cyclic review loop.

A `SupplyChainAnalyst` accepts an audit from either `GENERATED` or `UNDER_REVIEW`, moving it to the terminal `ACCEPTED` state; accepting from any other state is rejected with `ERR_AUDIT_NOT_ACTIONABLE`. A `Surgeon` may dispute an audit from those same two states — again `ERR_AUDIT_NOT_ACTIONABLE` elsewhere — but only the surgeon who owns the audited card may do so: the caller's `X-User-ID` must equal the audited card's `surgeon_id`, or the dispute is rejected with `ERR_FORBIDDEN_FOR_ROLE`. A dispute moves the audit to `DISPUTED` and stores the optional `comment` as the audit's `dispute_comment`, the latest comment being the one retained. The analyst then re-opens a `DISPUTED` audit for review — only from `DISPUTED`, otherwise `ERR_AUDIT_NOT_DISPUTED` — returning it to `UNDER_REVIEW`, from which it may be disputed again or finally accepted.

### 3.7. New Product Requests and the Value-Analysis Pipeline

New products enter the system only through value analysis, under strict segregation of duties. A `Surgeon` submits a product request naming the `proposed_item_name`, the `proposed_sku` the item should receive on approval, an `estimated_unit_cost_cents` of at least 1, and a `rationale` of at least 10 characters; optionally the request also proposes a `substitute_group`, a `consignment_flag` (default false), and a `replaces_item_id` naming an existing item this request would standardize away. The `proposed_sku` must not collide with an existing item's `sku` (`ERR_INVALID_REQUEST`), a referenced `replaces_item_id` must exist (`ERR_NOT_FOUND`), and the acting surgeon must be `ACTIVE` (`ERR_SURGEON_INACTIVE`). The request's `surgeon_id` is taken from the caller's `X-User-ID`, never from the payload, and the request lands in `SUBMITTED`. Requests are listed with `surgeon_id`, `status`, `replaces_item_id`, and `created_item_id` filters.

A `ValueAnalysisOfficer` opens review on a `SUBMITTED` request — any other state draws `ERR_REQUEST_NOT_UNDER_REVIEW` — moving it to `UNDER_REVIEW` and stamping `reviewing_officer_id` with their own opaque `X-User-ID`. While under review, officers endorse the request; each endorsement appends the acting officer's id to `endorser_ids`, increments `endorsements_count` (which always equals the number of distinct endorsers), and is rejected with `ERR_DUPLICATE_ENDORSEMENT` when the officer has already endorsed.

Approval requires quorum and an independent approver. The request must be `UNDER_REVIEW` (`ERR_REQUEST_NOT_UNDER_REVIEW`), its `endorsements_count` must be at least 2 (`ERR_QUORUM_NOT_MET`), the approving officer's `X-User-ID` must differ from `reviewing_officer_id` — the officer who opened review may never approve it, an attempt drawing `ERR_SOD_REVIEWER_CANNOT_APPROVE` (HTTP 403) — and the requesting surgeon must still be `ACTIVE` (`ERR_REQUESTER_INACTIVE`). Approval creates the new supply item in `ACTIVE` status with zero `on_hand_quantity`, built from the proposed fields — `proposed_sku` becoming its `sku`, `proposed_item_name` its `name`, `estimated_unit_cost_cents` its `unit_cost_cents`, with `substitute_group` and `consignment_flag` carried over — and records the new item as `created_item_id`; the SKU uniqueness check is enforced again at this moment. When `replaces_item_id` was set, that item transitions `ACTIVE → DISCONTINUED` in the same commit, which is what blocks it from new card lines and future publishes (§3.1). Rejection, from `UNDER_REVIEW` only, stores the supplied `rejection_reason` and moves the request to `REJECTED`. Both `APPROVED` and `REJECTED` are terminal.

### 3.8. Consignment Stewardship: Physical Counts and Billing Capture

Consignment stock is vendor-owned until opened, so its ledger is reconciled by physical count. A `MaterialsManager` records a count by naming the `supply_item_id` and the physically observed `counted_qty`, which may be zero but never negative (`ERR_INVALID_QUANTITY`). Only consignment items may be counted — an item whose `consignment_flag` is false is rejected with `ERR_NOT_CONSIGNMENT_ITEM`. At creation the count snapshots the item's `on_hand_quantity` as `system_qty_at_count`, computes `variance_qty` as `counted_qty` minus `system_qty_at_count`, and values the discrepancy as `variance_value_cents`, the variance multiplied by the item's `unit_cost_cents`; the count starts in `RECORDED`. Counts may be listed with `supply_item_id` and `status` filters.

Verification finalizes the count. Verifying is permitted only from `RECORDED` (`ERR_COUNT_NOT_RECORDED` otherwise) and moves the count to the terminal `VERIFIED` state, finalizing `variance_qty` and `variance_value_cents`. When the variance is non-zero, verification syncs the ledger by adding `variance_qty` to the item's `on_hand_quantity`; a zero variance leaves stock untouched.

The charges created at case completion are settled independently. A `MaterialsManager` captures a `PENDING` charge, moving it `PENDING → CAPTURED` to bill it; capturing from any other state is rejected with `ERR_CHARGE_INVALID_STATE`. Voiding compensates a charge from either `PENDING` or `CAPTURED`, moving it to the terminal `VOIDED` state — voiding a `CAPTURED` charge reduces the running total of captured `amount_cents` by that charge's amount — while voiding an already-`VOIDED` charge is rejected with `ERR_CHARGE_INVALID_STATE`. Charges may be listed with `case_id`, `supply_item_id`, `usage_record_id`, and `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource — registering a surgeon, creating an item, card, card line, case, product request, or consignment count, and releasing a case's pick list — return `201 Created`. Operations that act on an existing resource without creating a new one return `200 OK`. Removing a card line returns `204 No Content` with an empty body. All error responses use the envelope in §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/perioperative/surgeons` | Register a surgeon | SupplyChainAnalyst |
| GET | `/perioperative/surgeons/{id}` | Get a surgeon | Any |
| POST | `/perioperative/surgeons/{id}/deactivate` | Deactivate a surgeon | SupplyChainAnalyst |
| POST | `/perioperative/supply-items` | Create a supply item | SupplyChainAnalyst |
| GET | `/perioperative/supply-items` | List supply items, optional filters | Any |
| GET | `/perioperative/supply-items/{id}` | Get a supply item | Any |
| POST | `/perioperative/supply-items/{id}/stock-adjustments` | Adjust on-hand stock by a signed delta | MaterialsManager |
| POST | `/perioperative/preference-cards` | Create a DRAFT preference card (next version for the surgeon+procedure pair) | SupplyChainAnalyst |
| GET | `/perioperative/preference-cards` | List preference cards, optional filters | Any |
| GET | `/perioperative/preference-cards/{id}` | Get a preference card | Any |
| POST | `/perioperative/preference-cards/{id}/publish` | Publish a DRAFT card, superseding the ACTIVE sibling | SupplyChainAnalyst |
| POST | `/perioperative/preference-cards/{id}/retire` | Retire a card not in use by in-flight cases | SupplyChainAnalyst |
| POST | `/perioperative/preference-card-lines` | Add a line to a DRAFT card | SupplyChainAnalyst |
| GET | `/perioperative/preference-card-lines` | List card lines, optional filters | Any |
| GET | `/perioperative/preference-card-lines/{id}` | Get a card line | Any |
| DELETE | `/perioperative/preference-card-lines/{id}` | Remove a line from a DRAFT card | SupplyChainAnalyst |
| POST | `/perioperative/cases` | Schedule a case pinned to an ACTIVE card version | SupplyChainAnalyst |
| GET | `/perioperative/cases` | List cases, optional filters | Any |
| GET | `/perioperative/cases/{id}` | Get a case | Any |
| POST | `/perioperative/cases/{id}/release-pick-list` | Generate the pick list from the pinned card version | SupplyChainAnalyst |
| POST | `/perioperative/cases/{id}/repin-card` | Re-pin a SCHEDULED case to a different ACTIVE card (OCC-guarded) | SupplyChainAnalyst |
| POST | `/perioperative/cases/{id}/cancel` | Cancel a case before dispatch; restocks picked quantities | SupplyChainAnalyst |
| POST | `/perioperative/cases/{id}/complete` | Record usage and complete the case atomically | CirculatingNurse |
| GET | `/perioperative/pick-lists` | List pick lists, optional filters | Any |
| GET | `/perioperative/pick-lists/{id}` | Get a pick list | Any |
| POST | `/perioperative/pick-lists/{id}/begin-picking` | Start picking | CartTechnician |
| POST | `/perioperative/pick-lists/{id}/dispatch` | Dispatch a fully-staged case cart | CartTechnician |
| POST | `/perioperative/pick-lists/{id}/return` | Return the cart; record and restock unopened quantities | CartTechnician |
| GET | `/perioperative/pick-list-lines` | List pick list lines, optional filters | Any |
| GET | `/perioperative/pick-list-lines/{id}` | Get a pick list line | Any |
| POST | `/perioperative/pick-list-lines/{id}/pick` | Pick the full requested quantity of the planned item | CartTechnician |
| POST | `/perioperative/pick-list-lines/{id}/mark-short` | Flag a line as unavailable at the shelf | CartTechnician |
| POST | `/perioperative/pick-list-lines/{id}/substitute` | Resolve a SHORT line with an in-group substitute | CartTechnician |
| GET | `/perioperative/usage-records` | List usage records, optional filters | Any |
| GET | `/perioperative/usage-records/{id}` | Get a usage record | Any |
| GET | `/perioperative/card-audits` | List card accuracy audits, optional filters | Any |
| GET | `/perioperative/card-audits/{id}` | Get a card accuracy audit | Any |
| POST | `/perioperative/card-audits/{id}/accept` | Accept an audit from GENERATED or UNDER_REVIEW | SupplyChainAnalyst |
| POST | `/perioperative/card-audits/{id}/dispute` | Dispute an audit; owning surgeon only | Surgeon |
| POST | `/perioperative/card-audits/{id}/reopen-review` | Re-open a disputed audit for review | SupplyChainAnalyst |
| POST | `/perioperative/product-requests` | Surgeon requests a new supply item | Surgeon |
| GET | `/perioperative/product-requests` | List product requests, optional filters | Any |
| GET | `/perioperative/product-requests/{id}` | Get a product request | Any |
| POST | `/perioperative/product-requests/{id}/open-review` | Open value-analysis review | ValueAnalysisOfficer |
| POST | `/perioperative/product-requests/{id}/endorse` | Endorse a request under review (one per officer) | ValueAnalysisOfficer |
| POST | `/perioperative/product-requests/{id}/approve` | Approve when quorum is met; approver must differ from reviewer | ValueAnalysisOfficer |
| POST | `/perioperative/product-requests/{id}/reject` | Reject a request under review | ValueAnalysisOfficer |
| POST | `/perioperative/consignment-counts` | Record a physical consignment count | MaterialsManager |
| GET | `/perioperative/consignment-counts` | List consignment counts, optional filters | Any |
| GET | `/perioperative/consignment-counts/{id}` | Get a consignment count | Any |
| POST | `/perioperative/consignment-counts/{id}/verify` | Verify a count; apply the stock adjustment when variance is non-zero | MaterialsManager |
| GET | `/perioperative/consignment-charges` | List consignment charges, optional filters | Any |
| GET | `/perioperative/consignment-charges/{id}` | Get a consignment charge | Any |
| POST | `/perioperative/consignment-charges/{id}/capture` | Capture (bill) a pending consignment charge | MaterialsManager |
| POST | `/perioperative/consignment-charges/{id}/void` | Void a pending or captured charge (compensation) | MaterialsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_QUANTITY` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CARD_NOT_DRAFT` | 409 Conflict |
| `ERR_CARD_EMPTY` | 409 Conflict |
| `ERR_ITEM_NOT_ACTIVE` | 409 Conflict |
| `ERR_CARD_IN_USE` | 409 Conflict |
| `ERR_SURGEON_INACTIVE` | 409 Conflict |
| `ERR_CARD_SURGEON_MISMATCH` | 409 Conflict |
| `ERR_PINNED_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_PICK_LIST_EXISTS` | 409 Conflict |
| `ERR_CASE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_CASE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_CASE_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_PICK_LIST_INVALID_STATE` | 409 Conflict |
| `ERR_LINE_NOT_PENDING` | 409 Conflict |
| `ERR_LINE_NOT_SHORT` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_SUBSTITUTE_GROUP_MISMATCH` | 409 Conflict |
| `ERR_SUBSTITUTE_PRICE_THRESHOLD` | 402 Payment Required |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_SURGEON_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_CARD_LINE` | 409 Conflict |
| `ERR_USAGE_EXCEEDS_OPENED` | 422 Unprocessable Entity |
| `ERR_LINE_CASE_MISMATCH` | 409 Conflict |
| `ERR_CONSIGNMENT_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_SOD_REVIEWER_CANNOT_APPROVE` | 403 Forbidden |
| `ERR_DUPLICATE_ENDORSEMENT` | 409 Conflict |
| `ERR_REQUEST_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_REQUESTER_INACTIVE` | 409 Conflict |
| `ERR_AUDIT_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_AUDIT_NOT_DISPUTED` | 409 Conflict |
| `ERR_NOT_CONSIGNMENT_ITEM` | 409 Conflict |
| `ERR_COUNT_NOT_RECORDED` | 409 Conflict |
| `ERR_CHARGE_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
