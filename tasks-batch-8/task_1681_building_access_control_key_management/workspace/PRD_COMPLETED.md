# Building Access Control API — Product Requirements Document

## 1. Introduction

A building security office lives and dies by three questions: who can open which door, when, and what happens when something goes wrong. This document specifies a Building Access Control & Key Management API that answers all three as a single, coherent system. The platform tracks the physical credential inventory (metal keys, fobs, cards) issued to residents, staff, and vendors; models the master-key hierarchy that determines which cores a lost credential can actually open; and drives the operational response — rekey campaigns, work orders, vendor badge expiry, propped-door alerts, and the billing that follows.

The domain is deliberately conservative about trust. A lost key is not just a note in a log: it compromises a node in the master-key hierarchy, flags every lock whose security depends on that node, opens an incident for the security desk, and ultimately produces a rekey campaign with real dollar amounts attached. Move-outs produce deposit settlements; terminations cascade credential deactivations; and the access decision itself is an ordered rule chain with exactly one winning outcome. Throughout, the system runs against a single logical clock so that every timestamped rule — expiry windows, propped-door thresholds, retention horizons — is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that apply uniformly across the API: how callers authenticate, what responses look like, how lists paginate, and the cross-cutting invariants every endpoint honors.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID` identifying the acting user and `X-User-Role` naming their operational capacity. The recognized roles are `SecurityAdmin`, `SecurityOfficer`, `FrontDesk`, `Resident`, and `Vendor`. A request with a missing header, an unrecognized role, or — for entity-backed roles — an id that does not resolve to a persisted `Person` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint, or whose ownership check fails, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The five roles split by identity model. For `SecurityAdmin`, `SecurityOfficer`, and `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on mutations it makes but never compares it to any entity's `id`. For `Resident` and `Vendor`, `X-User-ID` is the `id` of the acting `Person`; ownership checks on any resource that references a `Person` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `Resident` or `Vendor` may read only their own `Person` record (path id must equal `X-User-ID`, else `ERR_FORBIDDEN`), may list credentials only with a `holder_person_id` filter equal to their own id, may list charges only with a `person_id` filter equal to their own id, may pay only charges whose `person_id` equals their own id, and may report lost only credentials whose `holder_person_id` equals their own id.

`SecurityAdmin` is the superset role: it alone creates buildings, key nodes, and doors; patches doors; creates, patches, and deletes access groups; terminates staff and vendors; creates, approves, and cancels rekey campaigns; voids charges; and sets the logical clock. `SecurityOfficer` shares incident review, propped-alert handling, work-order lifecycle, access checks, and the run-ops checkpoint with `SecurityAdmin`. `FrontDesk` shares person registration, move-out, credential intake/issue/return, charge issuance, and door close with `SecurityAdmin`. The audit trail — listing or reading access events — is restricted to `SecurityAdmin` and `SecurityOfficer`; `FrontDesk` is excluded from those two endpoints specifically.

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
- A request to an unrecognized path is rejected with `ERR_NOT_FOUND` (HTTP 404), and a request using an unsupported method on a recognized path is rejected with `ERR_INVALID_REQUEST` (HTTP 405); both use this same error envelope.

### 2.3. Pagination

List endpoints paginate via two query parameters. `limit` sets the maximum number of rows returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — a non-integer `limit` falls back to the default, and an out-of-range one is clamped to the nearest bound rather than rejected. `offset` sets the number of rows skipped and defaults to 0, with a non-integer or negative value likewise falling back to 0. The `meta` object of every list response includes `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of rows returned is less than `total_count`.

Every list endpoint returns rows ordered by `created_at` ascending, with the entity's per-building monotone minting counter `seq` ascending as the tie-break (for `RekeyCampaign` that same per-building counter is named `rekey_seq`; `AccessEvent` uses its building-scoped `seq`). `limit` and `offset` paginate over that combined ordering.

### 2.4. The Logical Clock

Every timestamp the system records and every time rule it evaluates reads a single logical clock, never the wall clock. At server startup, before any adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `SecurityAdmin`-only test-driving capability advances the clock by accepting a `to_iso8601` field and setting the current instant to it — a missing or unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a successful set returns a `data` object carrying `current_utc` echoing the new instant; the server must not fall back to wall-clock time under any circumstance. All persisted timestamps — `created_at`, `updated_at`, `issued_at`, `lost_at`, `moved_out_at`, `occurred_at`, `opened_at`, `completed_at`, `scheduled_start`, `scheduled_end` — are ISO 8601 UTC with three fractional digits.

### 2.5. Common Resource Properties

Every primary resource carries `id` (a server-minted UUID with no type prefix), `created_at` (ISO 8601 UTC, three fractional digits), `updated_at` (same format, refreshed on any mutation), and `version` (an integer starting at 1, incremented on every mutation). The exception is `AccessEvent`: audit rows carry only `id` and `created_at`; both `updated_at` and `version` are absent because events are immutable once appended. Each entity also carries a per-building monotone minting counter `seq` (on `RekeyCampaign` this field is named `rekey_seq`) used as the list tie-break after `created_at`. Each entity kind keeps its own independent counter, so different kinds mint overlapping `seq` values within the same building; `Building` itself, not being building-scoped, carries no `seq`.

### 2.6. Monetary Values and Precision

All money amounts are integer cents: `key_deposit_cents`, `base_fee_cents`, `per_door_fee_cents`, `per_key_reissue_fee_cents`, `actual_cost_cents`, `amount_cents`, `deposit_cents`, `provisional_refund_cents`, `final_forfeit_total_cents`, `final_refund_cents`, `estimated_cost_cents`, `final_cost_cents`, and `paid_amount_cents` are all integers. Where a percentage uplift applies (the administrative surcharge on forfeiture lines, the emergency surcharge on a rekey's door portion), the multiplied value is rounded half-up to integer cents; the rekey door portion is rounded exactly once, and forfeiture lines are rounded per line before any summing.

### 2.7. Optimistic Concurrency Control

Two write operations take an explicit optimistic-concurrency guard, and no others do. A request to patch an access group must carry `expected_access_group_version` holding the group's `version` as the client last observed it; if another writer has advanced the group's `version` since that observation — for example by editing `door_ids`, `person_ids`, or the schedule — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the group is stale. The same rule governs patching a door: the request must carry `expected_door_version` matching the door's current `version`, and a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

### 2.8. Building Scoping and Cross-Building Integrity

Every operational entity belongs to exactly one `Building`, referenced by `building_id`, and references across entities must stay inside a single building. A key node's `parent_id`, a credential's `key_node_id`, a door's `key_node_id`, the doors and persons named in an access group's `door_ids` and `person_ids`, a campaign's `key_node_id`, and a work order's `door_id` must all resolve to resources in the same building as the enclosing operation; any cross-building reference is rejected with `ERR_CROSS_BUILDING_REFERENCE` (HTTP 422). That list is exhaustive: other foreign keys — an issuance's `person_id`, a campaign's `incident_id` and `bill_person_id`, and a work order's `bill_person_id` — are validated for existence only and are never building-checked.

### 2.9. Validation Ordering

When a request fails for more than one reason, the rejection is deterministic because validations run in a fixed priority order. Authentication and authorization come first: header presence, role recognition, and entity-backed id resolution (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN`). Ownership checks that can be decided without loading the target — the own-record `Person` read and the self-filter rules on the credential and charge lists — run here as well, while ownership checks that require the persisted resource (reporting a credential lost, paying a charge) run immediately after that resource resolves, so an unknown id there draws `ERR_NOT_FOUND` rather than `ERR_FORBIDDEN`. Existence of path identifiers and body-supplied foreign keys follows role permission, validated left-to-right along the URL path (`ERR_NOT_FOUND`). Next is the optimistic-concurrency check (`ERR_STALE_VERSION`) on the two OCC-guarded patch operations. State-transition guards come after that — credential issuable/issued, person `ACTIVE`, and the incident/campaign/work-order/charge/alert guards (the various HTTP 409 codes). Then security-critical business rules (`ERR_PERSON_INACTIVE`, `ERR_MASTER_KEY_STAFF_ONLY`), then cross-building and cross-entity state references (`ERR_CROSS_BUILDING_REFERENCE`, `ERR_INCIDENT_NOT_REVIEWED`, `ERR_REKEY_REQUIRES_LOST_CREDENTIAL`), then uniqueness, hierarchy, capacity, and scope constraints (`ERR_DOOR_CODE_EXISTS`, `ERR_SERIAL_EXISTS`, `ERR_KEY_HIERARCHY_INVALID`, `ERR_CREDENTIAL_LIMIT_EXCEEDED`, `ERR_VENDOR_CREDENTIAL_WINDOW_OVERLAP`, `ERR_VENDOR_BADGE_POOL_EXHAUSTED`, `ERR_WORK_ORDER_OVERLAP`, `ERR_REKEY_SCOPE_EMPTY`), then temporal sanity (`ERR_EXPIRY_REQUIRED_FOR_VENDOR`, `ERR_VALIDITY_WINDOW_INVALID`, `ERR_SCHEDULE_INVALID`), and finally fiscal rules (`ERR_PAYMENT_AMOUNT_MISMATCH`, `ERR_BILL_TARGET_INVALID`). Orthogonal to this chain, structural body validation — a missing required field, a value of the wrong type, an unparseable timestamp or HH:MM value, or a value outside a field's enumerated set — is rejected with `ERR_INVALID_REQUEST` (HTTP 400), raised at the point the handler consumes the field.

### 2.10. Nested Resource Retrieval

Where a path nests one resource under another, identifiers are validated left-to-right: the first path identifier that does not resolve to an existing resource produces the `ERR_NOT_FOUND` rejection, and no later identifier is examined. The same order applies to body-supplied foreign keys once path validation has passed.

## 3. Business Logic & Workflows

### 3.1. Setting Up a Building and Its Master-Key Hierarchy

A `SecurityAdmin` onboards a property by creating a `Building` with a display `name` and an optional policy/rate configuration. Every omitted field takes a default: `audit_retention_days` defaults to 90 (the days an access event stays unarchived before run-ops archives it), `alert_escalation_minutes` defaults to 30 (how long a propped-door alert may sit unacknowledged before escalation), `vendor_badge_pool_max` defaults to 10 (the maximum number of concurrently live vendor temporary credentials building-wide), `default_propped_threshold_seconds` defaults to 120, `base_fee_cents` defaults to 15000, `per_door_fee_cents` to 7500, `per_key_reissue_fee_cents` to 2500, and `emergency_surcharge_pct` to 20 (the percent surcharge on the door portion when a rekey campaign finishes outside business hours). Business hours are defined by `business_open_utc` (default "08:00", an HH:MM UTC start that is inclusive) and `business_close_utc` (default "18:00", an HH:MM UTC end that is exclusive). A building also carries `ops_run_index`, a system counter that starts at 0 and increments once per run-ops checkpoint. Reading a building is open to all five roles.

Within a building, the master-key hierarchy is a tree of `KeyNode` records. Each node is created with a `building_id`, a human `label` (such as "Master A" or "Floor-3 change"), and a `level` drawn from exactly `GRAND_MASTER`, `MASTER`, `SUB_MASTER`, `CHANGE`. A node may name a `parent_id`; when present, the parent's level must sit above the child's along the chain `GRAND_MASTER` → `MASTER` → `SUB_MASTER` → `CHANGE` by one or two steps — a child may skip a single intermediate level (so `MASTER` → `CHANGE` is accepted) but may not skip two (so `GRAND_MASTER` → `CHANGE` is rejected) — and when absent the node is a root whose level must be either `GRAND_MASTER` or `MASTER`. Any violation of that adjacency or root rule is rejected with `ERR_KEY_HIERARCHY_INVALID`. New nodes start with `status` `ACTIVE` and a null `supersedes_node_id`; the system later uses `supersedes_node_id` to link each node to the successor minted for it by an approved rekey campaign.

Three computed counters describe a node's inventory at any moment, counting only credentials pinned to that exact node (never the subtree): `stock_credential_count` is the number with `status` `IN_STOCK`, `issued_credential_count` the number `ISSUED`, and `lost_credential_count` the number `LOST`. Nodes are listed with optional filters on `building_id`, `parent_id`, `status`, and `supersedes_node_id`, alongside the standard pagination parameters.

### 3.2. Doors, People, and the Credential Lifecycle

A `Door` is created by a `SecurityAdmin` with a `building_id`, a `door_code` unique within that building (duplicates rejected `ERR_DOOR_CODE_EXISTS`), and a `key_node_id` that must point at a `CHANGE`-level node — pinning a door to any higher level is `ERR_KEY_HIERARCHY_INVALID`. An optional `bitting_code` (default "STANDARD" — an omitted or empty value alike yields "STANDARD") records the current lock-core bitting; it is rotated to the successor node's label when a rekey completes. An optional `propped_threshold_seconds` (which must be an integer of at least 1, else `ERR_INVALID_REQUEST`) overrides how long the door may stand open before run-ops raises an alert; when omitted, the door inherits the building's `default_propped_threshold_seconds`. A new door starts with `hardware_status` `OPERATIONAL`, `core_status` `ACTIVE`, and `open_since` null. Doors can be listed with `building_id`, `key_node_id`, `hardware_status`, and `core_status` filters, and patched later to change `propped_threshold_seconds` under the OCC rule of §2.7, which bumps `version` by 1 — a patch that supplies no `propped_threshold_seconds` (or a null one) changes nothing yet still bumps `version` and refreshes `updated_at`.

People are registered by `FrontDesk` or `SecurityAdmin` with a `full_name`, a `kind` of `RESIDENT`, `STAFF`, or `VENDOR`, an optional `employer_name` (typical for vendors), and a `key_deposit_cents` (default 0). `unit_label` is required exactly when `kind` is `RESIDENT`; omitting it there is `ERR_INVALID_REQUEST`. Every person starts with `status` `ACTIVE`; `moved_out_at` stays null until a move-out occurs. Persons are listable by `building_id`, `kind`, and `status`.

Credentials enter the world through `FrontDesk` or `SecurityAdmin` as stock: a `serial_no` unique within the building (else `ERR_SERIAL_EXISTS`), a `type` of `METAL_KEY`, `FOB`, or `CARD`, and a `key_node_id` naming the hierarchy node whose locks the credential operates. A new credential has `status` `IN_STOCK`, null `holder_person_id`, null `issued_at`, null `expires_at`, null `lost_at`, and null `deactivated_reason`. Credentials are listable with `building_id`, `key_node_id`, `holder_person_id`, `status`, and `type` filters; `Resident` and `Vendor` callers must filter `holder_person_id` to their own id.

Issuance moves a credential from `IN_STOCK` to `ISSUED`. The issuing request carries the target `person_id` and, for vendors only, an `expires_at`. The guard chain runs as follows. The credential must currently be `IN_STOCK`, else `ERR_CREDENTIAL_NOT_ISSUABLE`. The target person must exist (else `ERR_NOT_FOUND`) and be `ACTIVE` (else `ERR_PERSON_INACTIVE`). If the credential's key node sits above `CHANGE` level, the holder must be `STAFF`, else `ERR_MASTER_KEY_STAFF_ONLY`. The person must currently hold fewer than 5 credentials in `ISSUED`, else `ERR_CREDENTIAL_LIMIT_EXCEEDED`. For a `VENDOR` holder, three additional rules apply in that order: the vendor must not already hold another live credential — one `ISSUED` whose `expires_at` is still in the future — else `ERR_VENDOR_CREDENTIAL_WINDOW_OVERLAP`; the building-wide count of live vendor credentials must be strictly below the building's `vendor_badge_pool_max`, else `ERR_VENDOR_BADGE_POOL_EXHAUSTED`; and `expires_at` is required (`ERR_EXPIRY_REQUIRED_FOR_VENDOR` if absent) and must lie strictly in the future (`ERR_VALIDITY_WINDOW_INVALID` if not). For any non-vendor holder, supplying `expires_at` at all is `ERR_INVALID_REQUEST`. On success the credential's `holder_person_id` is set to the person, `issued_at` to the current logical instant, and `expires_at` exactly as supplied for a vendor.

The credential lifecycle is cyclic around stock: returning an `ISSUED` credential — again `ERR_CREDENTIAL_NOT_ISSUED` guards the precondition — clears `holder_person_id`, `issued_at`, and `expires_at`, putting it back to `IN_STOCK` where it may be issued again. Reporting a credential lost requires it to be `ISSUED` (same `ERR_CREDENTIAL_NOT_ISSUED` guard); a `Resident` or `Vendor` caller may report only a credential whose `holder_person_id` matches their `X-User-ID`, else `ERR_FORBIDDEN`. A report stamps `lost_at` to now and deliberately retains `holder_person_id` for audit and settlement. The loss then cascades outward in three hops, described in §3.4. Deactivation is always system-driven: a credential leaves `IN_STOCK`, `ISSUED`, or `LOST` for `DEACTIVATED` with `deactivated_reason` one of `MOVE_OUT`, `TERMINATION`, `EXPIRED`, `REKEY`, or `INCIDENT`, retaining `holder_person_id` and (when present) `lost_at` for the record. Deactivation from `ISSUED` under the `REKEY` reason additionally creates a `KEY_REISSUE` charge, described in §3.5; deactivation from `IN_STOCK` or `LOST` never creates that charge.

### 3.3. Access Groups and the Access Decision

An `AccessGroup` ties people to doors across a weekly schedule. A `SecurityAdmin` creates one with a `building_id`, a `name`, a non-empty `days_of_week` subset of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`, and a window given by `window_start_utc` (HH:MM UTC, inclusive) and `window_end_utc` (HH:MM UTC, exclusive). The two window bounds must differ — equal bounds are `ERR_SCHEDULE_INVALID` — and a start later than the end is meaningful: the window wraps past midnight. `door_ids` and `person_ids` default to empty arrays; every id in them must belong to the same building (`ERR_CROSS_BUILDING_REFERENCE`) and every person must be `ACTIVE` (`ERR_PERSON_INACTIVE`). The group may be listed with `building_id`, `door_id`, and `person_id` filters — the latter two matching groups whose arrays contain the value — and patched to replace `name`, `door_ids`, `person_ids`, `days_of_week`, `window_start_utc`, or `window_end_utc` under the OCC rule of §2.7 (each listed field is replaced only when supplied non-null — omitted or null fields keep their current values — and the same same-building, active-person, and distinct-window-bounds checks re-apply on patch, the last comparing the effective post-patch bounds when only one bound is supplied), bumping `version` by 1. Groups can also be deleted outright.

The access decision — the question of whether a presented credential opens a door right now — is evaluated by an ordered rule chain, and the first failure decides the outcome. The chain runs: (1) the presented credential must exist, else the request itself fails `ERR_NOT_FOUND`; (2) the credential's `status` must be `ISSUED`, else the outcome is `DENIED_CREDENTIAL_NOT_ISSUED`; (3) if the credential carries an `expires_at` and now is at or past it, the outcome is `DENIED_CREDENTIAL_EXPIRED`; (4) the covering groups are those access groups of the door's building whose `person_ids` contain the credential's holder and whose `door_ids` contain the door — if none exist, the outcome is `DENIED_NOT_AUTHORIZED`; (5) if no covering group's schedule contains the current instant, the outcome is `DENIED_OUTSIDE_WINDOW`; (6) otherwise the outcome is `GRANTED`. Holder activity is enforced upstream of this chain: issuance requires an `ACTIVE` person and move-out or termination cascade-deactivates `ISSUED` credentials, so an inactive holder's credential never survives to step 2 as `ISSUED`.

Schedule containment at step 5 works on UTC minute-of-day and weekday. Let the window's `window_start_utc` and `window_end_utc` be expressed as minutes since 00:00 UTC, let the current instant's minute-of-day and UTC weekday be the test point (seconds are ignored — the comparison is minute-precision), and require the current UTC weekday to be a member of `days_of_week`. When the start is earlier than the end, containment means the test minute is greater than or equal to the start and strictly less than the end — a half-open interval. When the start is later than the end, containment means the test minute is at or after the start, or strictly before the end — the overnight wrap — and day membership still refers to the UTC weekday of the current instant. Equal start and end never reach evaluation because group writes reject them.

The access check itself is invoked by `SecurityAdmin`, `SecurityOfficer`, or `FrontDesk` with a `credential_id` and a `mode`. Under mode `RECORDED`, an `AccessEvent` row is appended capturing `building_id` (copied from the door), `credential_id`, `door_id`, the logical-clock `occurred_at`, and the winning `outcome`; additionally, when the outcome is `GRANTED` and the door's `open_since` is currently null, `open_since` is set to now — but re-scans while the door already shows open do not refresh it. Under mode `SIMULATED`, the same outcome is computed and returned but nothing is persisted. The response carries the `outcome`, the `credential_id`, the `door_id`, the evaluation timestamp `evaluated_at`, and the `access_event_id` of the appended row (null under `SIMULATED`).

### 3.4. Loss, Alerts, and the Incident Workflow

Reporting an issued credential lost fires a three-hop cascade. Hop 1 flips the credential's own `KeyNode` from `ACTIVE` to `COMPROMISED` (a no-op if the node is already `COMPROMISED` or `RETIRED`). Hop 2, caused by hop 1, sets `core_status` to `REKEY_REQUIRED` on every door whose `key_node_id` lies in the compromised node's subtree, including the node itself. Hop 3, also caused by hop 1, opens an `Incident` with `type` `LOST_CREDENTIAL`, `status` `OPEN`, the `credential_id` of the lost credential, and `responsible_person_id` set to the credential's `holder_person_id` at the moment of the report. Incidents are system-created only — there is no direct create endpoint — and every incident carries `building_id`, `type` (`LOST_CREDENTIAL` or `PROPPED_DOOR`), nullable `credential_id`/`door_id`/`alert_id`/`campaign_id` links, and a `seq`. Incidents are listable with filters on `building_id`, `type`, `status`, `credential_id`, `door_id`, `alert_id`, `responsible_person_id`, and `campaign_id`.

Incident handling is a review loop owned by `SecurityOfficer` or `SecurityAdmin`. Starting review moves `OPEN` → `UNDER_REVIEW` (from any other state, `ERR_INCIDENT_INVALID_STATE`). From `UNDER_REVIEW`, an operator may either dismiss the incident (`UNDER_REVIEW` → `DISMISSED`) or resolve it (`UNDER_REVIEW` → `RESOLVED`) by supplying a `resolution_action` of `NONE`, `REQUEST_REKEY`, or `DEACTIVATE_CREDENTIAL` plus an optional `resolution_note`. Three preconditions guard the resolve action in order: choosing `REQUEST_REKEY` requires the incident to be of `type` `LOST_CREDENTIAL` with a non-null `credential_id`, else `ERR_REKEY_REQUIRES_LOST_CREDENTIAL`; `REQUEST_REKEY` also requires the incident's `campaign_id` to still be null, else `ERR_CAMPAIGN_ALREADY_EXISTS`; and choosing `DEACTIVATE_CREDENTIAL` requires a non-null `credential_id`, else `ERR_INVALID_REQUEST`. Resolving with `REQUEST_REKEY` creates a `RekeyCampaign` in `PROPOSED` status whose `key_node_id` is the lost credential's node, whose `incident_id` is this incident, whose `bill_to` is `PERSON` when `responsible_person_id` is set and `BUILDING` otherwise, whose `bill_person_id` mirrors `responsible_person_id`, and whose scope counts and estimate are computed at creation; the incident's `campaign_id` is set to the new campaign. Resolving with `DEACTIVATE_CREDENTIAL` drives the linked credential — if it is currently `ISSUED` or `LOST` — to `DEACTIVATED` with `deactivated_reason` `INCIDENT`.

Resolved and dismissed incidents are not the end of the road: reopening moves `RESOLVED` → `UNDER_REVIEW` or `DISMISSED` → `UNDER_REVIEW` (from any other state, `ERR_INCIDENT_INVALID_STATE`), retaining the prior `resolution_action` and `resolution_note` for audit. A reopened incident may be resolved again, but `REQUEST_REKEY` remains blocked because `campaign_id` is already set — this revision loop exists precisely to let operators correct or complete a resolution without ever spawning a duplicate campaign.

Separately, doors watch for being propped open. A `ProppedDoorAlert` carries `building_id` and `door_id` copied from the door, an `opened_at` equal to the door's `open_since` at detection time, a `status` of `OPEN`, `ACKNOWLEDGED`, `ESCALATED`, or `RESOLVED`, a nullable `resolved_reason` (`MANUAL` or `DOOR_CLOSED`), and a nullable `incident_id` set when the alert escalates. A `SecurityOfficer` or `SecurityAdmin` acknowledges an `OPEN` alert (`OPEN` → `ACKNOWLEDGED`; from elsewhere, `ERR_ALERT_INVALID_STATE`). Resolution closes the alert with `resolved_reason` recorded: manual resolve accepts `OPEN`, `ACKNOWLEDGED`, or `ESCALATED` and stamps `MANUAL`; recording the door physically closed — which sets the door's `open_since` to null — auto-resolves any alert on that door in `OPEN` or `ACKNOWLEDGED` with `DOOR_CLOSED`, and closing a door whose `open_since` is already null succeeds without changing the door. An `ESCALATED` alert is deliberately not auto-resolved by door close: once escalated, the linked incident owns the case. Alerts are listable by `building_id`, `door_id`, `status`, and `incident_id`.

### 3.5. Rekey Campaigns, Work Orders, and the Re-Pinning Cascade

A rekey campaign re-pins every lock in one subtree of the key hierarchy. A `SecurityAdmin` proposes one with a `building_id`, a `key_node_id` naming the scope root, an optional originating `incident_id`, a `bill_to` of `BUILDING` (the default) or `PERSON`, and a `bill_person_id` that is required exactly when `bill_to` is `PERSON` — supplying it with `BUILDING`, or omitting it with `PERSON`, is `ERR_BILL_TARGET_INVALID`. The new campaign starts `PROPOSED`, is assigned its per-building `rekey_seq`, and immediately computes its estimate: `affected_door_count` counts doors whose `key_node_id` lies in the scope subtree with `core_status` `ACTIVE` or `REKEY_REQUIRED`, `affected_credential_count` counts credentials pinned in the subtree with `status` `ISSUED`, and `estimated_cost_cents` is the building's `base_fee_cents` plus `per_door_fee_cents` times the affected door count plus `per_key_reissue_fee_cents` times the affected credential count. The estimate is forward-looking — it snapshots current scope counts at standard rates and never applies the emergency surcharge. Campaigns list with `building_id`, `key_node_id`, `incident_id`, `status`, and `bill_person_id` filters; `final_cost_cents` and `completed_at` stay null until completion.

Approval (`PROPOSED` → `APPROVED`, `SecurityAdmin` only) runs three guards: the campaign must be `PROPOSED` (else `ERR_CAMPAIGN_INVALID_STATE`); the refreshed `affected_door_count` must be greater than 0 (else `ERR_REKEY_SCOPE_EMPTY`); and when an `incident_id` is attached, that incident must be in `UNDER_REVIEW` or `RESOLVED` — an incident still `OPEN` yields `ERR_INCIDENT_NOT_REVIEWED`. Approval refreshes the scope counts and estimate, then mints the successor subtree: for every node in the scope subtree, processed in order of level depth ascending, then `label` ascending, then `seq` ascending, a new `KeyNode` is created with the same `level`, a `label` equal to the original label suffixed with `-R` followed by the campaign's `rekey_seq`, a `parent_id` pointing at the successor of the original node's parent (null for the scope root), `supersedes_node_id` set to the original node's id, and `status` `ACTIVE`. Finally, for each affected door in `door_code` ascending order, a `MaintenanceWorkOrder` is created with `type` `REKEY`, `status` `OPEN`, the `campaign_id` set, `target_key_node_id` naming the successor of the door's current key node, and null `scheduled_start`/`scheduled_end`. Note that `REKEY` is reserved for campaign-generated orders; a manual work-order creation carrying that type is `ERR_INVALID_REQUEST`.

A campaign moves `APPROVED` → `IN_PROGRESS` automatically the moment its first linked work order starts, and `IN_PROGRESS` → `COMPLETED` automatically once every linked work order is `COMPLETED` or `CANCELLED` with at least one `COMPLETED`. Completion stamps `completed_at`, retires every node in the scope subtree (`ACTIVE` or `COMPROMISED` → `RETIRED`), and computes `final_cost_cents` from what actually happened: the door portion is the building's `base_fee_cents` plus the sum of `actual_cost_cents` over linked work orders in `COMPLETED` status (cancelled orders drop out); if `completed_at`'s UTC time-of-day, compared at minute precision with seconds ignored, falls outside the half-open business-hours interval from `business_open_utc` (inclusive) to `business_close_utc` (exclusive), that door-portion subtotal is multiplied by one plus `emergency_surcharge_pct` hundredths and rounded half-up to integer cents, the surcharge being rounded exactly once; the key portion is the sum of `amount_cents` over the campaign's linked `KEY_REISSUE` charges; and `final_cost_cents` is the door portion plus the key portion. Completion also creates a `Charge` of `kind` `REKEY_CAMPAIGN` in `DRAFT` whose `amount_cents` equals that door portion and whose `person_id` is the campaign's `bill_person_id` when `bill_to` is `PERSON`, null otherwise. Cancellation runs from `PROPOSED` or `APPROVED`: a `COMPLETED` or `CANCELLED` campaign is rejected with `ERR_CAMPAIGN_INVALID_STATE`, and any linked work order in `IN_PROGRESS` blocks cancellation with `ERR_CAMPAIGN_HAS_ACTIVE_WORK` regardless of the campaign's own state — so a campaign that has already auto-tipped to `IN_PROGRESS` surfaces the active-work error rather than the state error. Cancelling an `APPROVED` campaign cascades every linked `OPEN` work order to `CANCELLED`.

Manual maintenance is scheduled through work orders created by `SecurityOfficer` or `SecurityAdmin` with a `building_id`, a `door_id`, a `type` of `HARDWARE_REPAIR`, `INSPECTION`, or `BATTERY_REPLACE`, a `scheduled_start` and `scheduled_end` (the end must be strictly after the start, else `ERR_SCHEDULE_INVALID`), and an optional `bill_person_id`. The planned window must not intersect another `OPEN` or `IN_PROGRESS` order's window on the same door — windows whose endpoints merely touch do not intersect, and orders carrying no scheduled window (campaign-generated `REKEY` orders) never participate in this check — else `ERR_WORK_ORDER_OVERLAP`. Work orders list with `building_id`, `door_id`, `campaign_id`, `status`, `type`, `bill_person_id`, and `target_key_node_id` filters.

Starting a work order (`OPEN` → `IN_PROGRESS`) requires the door's `hardware_status` to be `OPERATIONAL`, else `ERR_DOOR_UNDER_MAINTENANCE` (state errors generally surface as `ERR_WORK_ORDER_INVALID_STATE`); starting flips the door to `UNDER_MAINTENANCE`, and when the order belongs to an `APPROVED` campaign this is the event that tips the campaign to `IN_PROGRESS`. Completing an `IN_PROGRESS` order records the supplied `actual_cost_cents` (required at completion), returns the door to `OPERATIONAL`, and — for `REKEY` orders only — fires the re-pinning cascade: hop 1 re-pins the door by setting `key_node_id` to `target_key_node_id`, rotating `bitting_code` to the target node's label, and restoring `core_status` to `ACTIVE`; hop 2, caused by hop 1, deactivates every credential pinned to the door's pre-rekey node that is not already `DEACTIVATED`, walking them in `created_at` ascending, `serial_no` ascending order and stamping `deactivated_reason` `REKEY`; hop 3, caused by hop 2, creates for each credential that was `ISSUED` at the moment of deactivation a `Charge` of `kind` `KEY_REISSUE` in `DRAFT` status with `amount_cents` equal to the building's `per_key_reissue_fee_cents`, the `campaign_id` set, and `person_id` per the campaign's `bill_to` rule. Each completion (or cancellation) then runs the campaign completion check: if every linked work order is now `COMPLETED` or `CANCELLED` with at least one `COMPLETED`, the campaign completes as described above — so even a cancel can be the event that finishes a campaign. Cancelling is allowed from `OPEN` only.

### 3.6. Charges, Move-Out Settlement, and the Run-Ops Checkpoint

All charges are system-created. A `Charge` carries `building_id`, a nullable `person_id` (null when billed to the building), a nullable `campaign_id` (set for `REKEY_CAMPAIGN` and `KEY_REISSUE` kinds), a `kind` of `MOVE_OUT_SETTLEMENT`, `REKEY_CAMPAIGN`, or `KEY_REISSUE`, an integer `amount_cents`, a `status` of `DRAFT`, `ISSUED`, `PAID`, or `VOID`, and — for settlements — a `deposit_cents` snapshot, `provisional_refund_cents`, `final_forfeit_total_cents`, `final_refund_cents`, a `line_items` array, and the anchoring `moved_out_at`; those settlement fields stay null on non-settlement kinds. Charges list with `building_id`, `person_id`, `campaign_id`, `kind`, and `status` filters; `Resident` and `Vendor` callers must filter `person_id` to their own id. Issuing moves `DRAFT` → `ISSUED` (guarded by `ERR_CHARGE_INVALID_STATE`), payment moves `ISSUED` → `PAID` and requires the supplied `paid_amount_cents` to equal `amount_cents` exactly (else `ERR_PAYMENT_AMOUNT_MISMATCH`; `Resident`/`Vendor` payers must own the charge, else `ERR_FORBIDDEN`), and voiding moves `DRAFT` or `ISSUED` → `VOID` (`SecurityAdmin` only).

Move-out is the settlement trigger. A `FrontDesk` or `SecurityAdmin` moves a person out — `ACTIVE` → `MOVED_OUT`, one of the two terminal person states alongside `TERMINATED` — only when the person is `ACTIVE` (else `ERR_PERSON_INVALID_STATE`) and of `kind` `RESIDENT` (else `ERR_PERSON_KIND_MISMATCH`). The transition stamps `moved_out_at` to now, deactivates every credential currently `ISSUED` to that person with `deactivated_reason` `MOVE_OUT`, removes the person's id from the `person_ids` of every access group in the building, and creates the settlement charge in `DRAFT`: `kind` `MOVE_OUT_SETTLEMENT`, `person_id` set, `deposit_cents` snapshotted from the person's `key_deposit_cents`, `moved_out_at` recorded, `line_items` holding the forfeiture lines for the credentials `ISSUED` at move-out, `provisional_refund_cents` computed, and `amount_cents` 0 while in draft. Termination is the parallel path — `ACTIVE` → `TERMINATED` — for `STAFF` and `VENDOR` persons (`SecurityAdmin` only; a `RESIDENT` target is `ERR_PERSON_KIND_MISMATCH`): it likewise deactivates the person's `ISSUED` credentials with `deactivated_reason` `TERMINATION` and strips group memberships, but creates no settlement charge — there is no deposit workflow for staff or vendors.

Each forfeiture line prices one lost or unreturned credential: the per-type fee is 1500 cents for a `METAL_KEY`, 4500 cents for a `FOB`, and 1501 cents for a `CARD`; each line's fee is uplifted by a 25 percent administrative surcharge and rounded half-up to integer cents per line first, and only then are lines summed — summing before rounding produces a different, incorrect result. Each line is a snapshot of `credential_id`, `type`, and `fee_cents`. The provisional variant, computed at move-out, forfeits only the credentials `ISSUED` at that instant and sets `provisional_refund_cents` to the deposit minus the line total, floored at zero. The final variant runs when the settlement charge is issued: it appends lines for credentials whose `lost_at` falls within the inclusive trailing window from 30 days before `moved_out_at` up to and including `moved_out_at` — membership judged by `lost_at` regardless of the credential's current status — with the provisional lines ordered first, each set internally ordered by the credential's `created_at` ascending then the credential's per-building minting counter `seq` ascending. It then sets `final_forfeit_total_cents` to the sum of all lines, `final_refund_cents` to the deposit minus that total floored at zero, and `amount_cents` to the total minus the deposit floored at zero. A resident with recent losses therefore sees a smaller final refund than the provisional one suggested.

The run-ops checkpoint — available to `SecurityAdmin` and `SecurityOfficer` — performs four duties in pinned order against the logical clock, then bumps the building's `ops_run_index` and `version`. First, the vendor expiry sweep: walking the building's credentials in `created_at` ascending, `serial_no` ascending order, every credential in `ISSUED` with a non-null `expires_at` at or before now is deactivated with `deactivated_reason` `EXPIRED` — the boundary is consistent with the access rule that a credential is valid only while now is strictly before `expires_at`. Second, the propped-door check: walking the building's doors in `door_code` ascending order, any door whose `open_since` is non-null and whose open duration in seconds is strictly greater than its `propped_threshold_seconds` gets a `ProppedDoorAlert` in `OPEN` with `opened_at` copied from `open_since` — but only when no alert for that door is already in `OPEN` or `ACKNOWLEDGED`; a duration exactly equal to the threshold raises nothing. Third, stale-alert escalation: walking the building's `OPEN` alerts in `created_at` ascending, `seq` ascending order, any alert that has remained `OPEN` for longer than the building's `alert_escalation_minutes` — measuring now minus its `created_at` — escalates to `ESCALATED`, spawning an `Incident` of `type` `PROPPED_DOOR` in `OPEN` status linked by `door_id` and `alert_id`, with the alert's `incident_id` set. Fourth, retention archival: the cutoff is now minus the building's `audit_retention_days`, and every `AccessEvent` whose `archived` flag is still false and whose `occurred_at` is strictly older than the cutoff is flipped to `archived` true, walking events in `occurred_at` ascending order; an event exactly at the cutoff is kept unarchived. Archived rows disappear from the audit-trail list unless the caller passes `include_archived` as true — the values `true`, `1`, and `yes`, case-insensitively, all count — though any archived event remains readable directly by its id. The checkpoint response reports the new `ops_run_index` plus four counts: `vendor_credentials_expired`, `propped_alerts_created`, `alerts_escalated`, and `events_archived`. The audit trail itself is queryable by `SecurityAdmin` and `SecurityOfficer` with `building_id`, `credential_id`, `door_id`, and `outcome` filters alongside `include_archived`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`; deleting an access group returns `204 No Content` with no body at all — no envelope. Request bodies, response payloads, and per-endpoint side effects are specified in §2 and §3 — this table is the HTTP contract only. Body fields beyond those specified are ignored rather than rejected.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/buildings` | Create a building with its policy/rate configuration | SecurityAdmin |
| GET    | `/buildings/{buildingId}` | Get a building | SecurityAdmin, SecurityOfficer, FrontDesk, Resident, Vendor |
| POST   | `/buildings/{buildingId}/run-ops` | Run the operations checkpoint (expiry sweep, propped check, escalation, retention, index bump) | SecurityAdmin, SecurityOfficer |
| POST   | `/key-nodes` | Create a master-key hierarchy node | SecurityAdmin |
| GET    | `/key-nodes` | List key nodes with computed credential counts | SecurityAdmin, SecurityOfficer, FrontDesk |
| GET    | `/key-nodes/{keyNodeId}` | Get a key node | SecurityAdmin, SecurityOfficer, FrontDesk |
| POST   | `/doors` | Create a door pinned to a change-level key node | SecurityAdmin |
| GET    | `/doors` | List doors | SecurityAdmin, SecurityOfficer, FrontDesk |
| GET    | `/doors/{doorId}` | Get a door | SecurityAdmin, SecurityOfficer, FrontDesk |
| PATCH  | `/doors/{doorId}` | Update a door's propped-open threshold; OCC-guarded | SecurityAdmin |
| POST   | `/doors/{doorId}/close` | Record the door physically closed; auto-resolve open/acknowledged alerts | SecurityOfficer, FrontDesk, SecurityAdmin |
| POST   | `/doors/{doorId}/access-checks` | Evaluate the access decision for a credential at this door (RECORDED or SIMULATED) | SecurityAdmin, SecurityOfficer, FrontDesk |
| GET    | `/access-events` | Query the audit trail; archived rows excluded unless requested | SecurityAdmin, SecurityOfficer |
| GET    | `/access-events/{accessEventId}` | Get a single audit event, archived or not | SecurityAdmin, SecurityOfficer |
| POST   | `/persons` | Register a resident, staff, or vendor person | FrontDesk, SecurityAdmin |
| GET    | `/persons` | List persons | SecurityAdmin, SecurityOfficer, FrontDesk |
| GET    | `/persons/{personId}` | Get a person; Resident/Vendor callers read their own record only | SecurityAdmin, SecurityOfficer, FrontDesk, Resident, Vendor |
| POST   | `/persons/{personId}/move-out` | Move a resident out; deactivate credentials, strip groups, draft the settlement | FrontDesk, SecurityAdmin |
| POST   | `/persons/{personId}/terminate` | Terminate a staff/vendor person; deactivate credentials and strip groups | SecurityAdmin |
| POST   | `/credentials` | Add a key, fob, or card to stock | FrontDesk, SecurityAdmin |
| GET    | `/credentials` | List credentials; Resident/Vendor callers filter to their own holdings | SecurityAdmin, SecurityOfficer, FrontDesk, Resident, Vendor |
| GET    | `/credentials/{credentialId}` | Get a credential | SecurityAdmin, SecurityOfficer, FrontDesk |
| POST   | `/credentials/{credentialId}/issue` | Issue a stocked credential to an active person | FrontDesk, SecurityAdmin |
| POST   | `/credentials/{credentialId}/return` | Return an issued credential to stock | FrontDesk, SecurityAdmin |
| POST   | `/credentials/{credentialId}/report-lost` | Report an issued credential lost; cascade compromise and incident creation | SecurityAdmin, FrontDesk, Resident, Vendor |
| POST   | `/access-groups` | Create an access group with doors, members, and a weekly window | SecurityAdmin |
| GET    | `/access-groups` | List access groups; door/person filters match array membership | SecurityAdmin, SecurityOfficer, FrontDesk |
| GET    | `/access-groups/{accessGroupId}` | Get an access group | SecurityAdmin, SecurityOfficer, FrontDesk |
| PATCH  | `/access-groups/{accessGroupId}` | Replace group name, membership, doors, or schedule; OCC-guarded | SecurityAdmin |
| DELETE | `/access-groups/{accessGroupId}` | Delete an access group | SecurityAdmin |
| GET    | `/incidents` | List incidents | SecurityAdmin, SecurityOfficer, FrontDesk |
| GET    | `/incidents/{incidentId}` | Get an incident | SecurityAdmin, SecurityOfficer, FrontDesk |
| POST   | `/incidents/{incidentId}/start-review` | Move an open incident under review | SecurityOfficer, SecurityAdmin |
| POST   | `/incidents/{incidentId}/resolve` | Resolve an under-review incident with a resolution action | SecurityOfficer, SecurityAdmin |
| POST   | `/incidents/{incidentId}/dismiss` | Dismiss an under-review incident | SecurityOfficer, SecurityAdmin |
| POST   | `/incidents/{incidentId}/reopen` | Reopen a resolved or dismissed incident | SecurityOfficer, SecurityAdmin |
| POST   | `/rekey-campaigns` | Propose a rekey over a key-node subtree; compute scope and estimate | SecurityAdmin |
| GET    | `/rekey-campaigns` | List rekey campaigns | SecurityAdmin, SecurityOfficer, FrontDesk |
| GET    | `/rekey-campaigns/{campaignId}` | Get a rekey campaign | SecurityAdmin, SecurityOfficer, FrontDesk |
| POST   | `/rekey-campaigns/{campaignId}/approve` | Approve a campaign; mint successor subtree and per-door rekey orders | SecurityAdmin |
| POST   | `/rekey-campaigns/{campaignId}/cancel` | Cancel a proposed or approved campaign; cancel its open work orders | SecurityAdmin |
| POST   | `/work-orders` | Create a manual repair, inspection, or battery-replacement order | SecurityOfficer, SecurityAdmin |
| GET    | `/work-orders` | List work orders | SecurityAdmin, SecurityOfficer, FrontDesk |
| GET    | `/work-orders/{workOrderId}` | Get a work order | SecurityAdmin, SecurityOfficer, FrontDesk |
| POST   | `/work-orders/{workOrderId}/start` | Start an open work order; door enters maintenance | SecurityOfficer, SecurityAdmin |
| POST   | `/work-orders/{workOrderId}/complete` | Complete an in-progress order; rekey orders re-pin the door and cascade | SecurityOfficer, SecurityAdmin |
| POST   | `/work-orders/{workOrderId}/cancel` | Cancel an open work order; may complete the parent campaign | SecurityOfficer, SecurityAdmin |
| GET    | `/charges` | List charges; Resident/Vendor callers filter to their own | SecurityAdmin, SecurityOfficer, FrontDesk, Resident, Vendor |
| GET    | `/charges/{chargeId}` | Get a charge | SecurityAdmin, SecurityOfficer, FrontDesk |
| POST   | `/charges/{chargeId}/issue` | Issue a draft charge; settlements run the final variant | FrontDesk, SecurityAdmin |
| POST   | `/charges/{chargeId}/pay` | Pay an issued charge; amount must match exactly | Resident, Vendor, FrontDesk |
| POST   | `/charges/{chargeId}/void` | Void a draft or issued charge | SecurityAdmin |
| GET    | `/propped-alerts` | List propped-door alerts | SecurityAdmin, SecurityOfficer, FrontDesk |
| GET    | `/propped-alerts/{alertId}` | Get a propped-door alert | SecurityAdmin, SecurityOfficer, FrontDesk |
| POST   | `/propped-alerts/{alertId}/acknowledge` | Acknowledge an open alert | SecurityOfficer, SecurityAdmin |
| POST   | `/propped-alerts/{alertId}/resolve` | Manually resolve an open, acknowledged, or escalated alert | SecurityOfficer, SecurityAdmin |
| POST   | `/_clock/set_current_utc` | Set the logical clock used by every timestamp and time rule | SecurityAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CREDENTIAL_NOT_ISSUABLE` | 409 |
| `ERR_CREDENTIAL_NOT_ISSUED` | 409 |
| `ERR_PERSON_INVALID_STATE` | 409 |
| `ERR_PERSON_KIND_MISMATCH` | 409 |
| `ERR_PERSON_INACTIVE` | 422 |
| `ERR_MASTER_KEY_STAFF_ONLY` | 422 |
| `ERR_CREDENTIAL_LIMIT_EXCEEDED` | 422 |
| `ERR_VENDOR_CREDENTIAL_WINDOW_OVERLAP` | 422 |
| `ERR_VENDOR_BADGE_POOL_EXHAUSTED` | 422 |
| `ERR_EXPIRY_REQUIRED_FOR_VENDOR` | 422 |
| `ERR_VALIDITY_WINDOW_INVALID` | 422 |
| `ERR_SCHEDULE_INVALID` | 422 |
| `ERR_KEY_HIERARCHY_INVALID` | 422 |
| `ERR_CROSS_BUILDING_REFERENCE` | 422 |
| `ERR_DOOR_CODE_EXISTS` | 422 |
| `ERR_SERIAL_EXISTS` | 422 |
| `ERR_DOOR_UNDER_MAINTENANCE` | 409 |
| `ERR_INCIDENT_INVALID_STATE` | 409 |
| `ERR_INCIDENT_NOT_REVIEWED` | 422 |
| `ERR_REKEY_REQUIRES_LOST_CREDENTIAL` | 422 |
| `ERR_CAMPAIGN_INVALID_STATE` | 409 |
| `ERR_CAMPAIGN_ALREADY_EXISTS` | 409 |
| `ERR_CAMPAIGN_HAS_ACTIVE_WORK` | 409 |
| `ERR_REKEY_SCOPE_EMPTY` | 422 |
| `ERR_WORK_ORDER_INVALID_STATE` | 409 |
| `ERR_WORK_ORDER_OVERLAP` | 422 |
| `ERR_CHARGE_INVALID_STATE` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_BILL_TARGET_INVALID` | 422 |
