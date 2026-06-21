# Wedding RSVP & Gift Registry API — Product Requirements Document

## 1. Introduction

Planning a wedding fragments naturally into two parallel workstreams that nevertheless share a single guest list, a single calendar of deadlines, and a single couple acting as the final arbiter: the RSVP track, where invitations go out, meal selections come back, and a seating chart is reconciled against caterer capacity; and the gift registry track, where purchases stream in from multiple consumer platforms and must be deduplicated, attributed, and eventually thanked for. The Wedding RSVP & Gift Registry API exists to keep these two tracks consistent in real time — so that a guest's last-minute decline does not leave their seat occupied in a "finalized" chart, and so that a cross-platform duplicate purchase does not silently double-count toward a fulfilled gift.

The system is operated by four distinct callers — the engaged couple managing their own event, the invited guests acting through opaque invitation tokens, the server-to-server platform integrations that push gift transactions in, and the platform's own administrators — each with a tightly scoped set of capabilities. Every change to a wedding's posture, every guest RSVP, and every duplicate-purchase decision is journaled through state machines whose preconditions are deliberately tight: the system rejects the wrong action before it can corrupt the downstream aggregate, rather than discovering inconsistency afterward.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers identifying the caller: `X-User-ID` to identify the acting principal and `X-User-Role` to specify their operational capacity. Requests missing either header, or carrying values that fail well-formedness checks, are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the caller's role is well-formed but the role itself is not authorized for the target endpoint per the role matrix in §4, the rejection is `ERR_FORBIDDEN` (HTTP 403); the same code is returned when a `Couple` operator attempts to act on a wedding whose `couple_user_id` does not match their `X-User-ID`.

Four roles are recognized, spelled exactly as follows:

- `Couple` — the engaged couple operating their own wedding. The `Couple` identity is **opaque**: `X-User-ID` is treated as the `couple_user_id` stored on each `Wedding`, and the server does not look it up against any separate persisted entity. Ownership checks on a wedding therefore compare the wedding's `couple_user_id` field directly to `X-User-ID`.
- `GuestSelf` — an invited guest acting through their personal invitation. The `GuestSelf` identity is **entity-backed by `Guest`**: `X-User-ID` is the `id` of the acting `Guest`, and any operation `GuestSelf` performs on a `Guest` or that guest's `PlusOne` requires the resource's foreign-key chain (the `PlusOne.guest_id` for a plus-one) to lead back to that same `Guest.id`. In addition, `GuestSelf` requests must carry an `X-Invitation-Token` header whose value matches the `Guest.invitation_token` minted by the server when the guest was first added; a missing or mismatched token is itself `ERR_UNAUTHENTICATED`.
- `PlatformIntegration` — a server-to-server integration that ingests gift purchases from external platforms. The `PlatformIntegration` identity is **opaque**: `X-User-ID` is a platform-integration identifier and is not compared to any persisted entity's `id`. The server may record it on derived audit fields but never treats it as a foreign key.
- `PlatformAdmin` — an operator of the platform itself, with broad read access across all weddings and the ability to archive a wedding or to drive the test clock. The `PlatformAdmin` identity is **opaque**: `X-User-ID` is an operator identifier and, like `PlatformIntegration`, is not bound to any persisted entity.

The creation of a wedding (the bootstrap operation) is exempt from a pre-existing wedding existence check but still requires the authentication headers and the `Couple` role.

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

All list endpoints accept two query parameters that govern paging: `limit` controls the maximum number of rows returned and defaults to 10, with a minimum of 1 and a maximum of 100; `offset` controls how many rows to skip and defaults to 0 with no upper bound beyond the size of the underlying set. Unless an endpoint explicitly declares another order, list responses are sorted by each row's `created_at` in ascending order, and the `meta` block carries `limit`, `offset`, `total_count`, and `has_more` so a client can paginate without re-counting.

### 2.4. Common Resource Properties

Every resource the API exposes — `Wedding`, `MealOption`, `Table`, `Guest`, `PlusOne`, `SeatingAssignment`, `RegistryItem`, `Purchase`, and `ThankYouNote` — receives the following system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix and no embedded semantics. Clients never supply `id` on create.
- `created_at` (string): the ISO 8601 UTC timestamp with three fractional digits at which the row was first written. Immutable after creation.
- `updated_at` (string): the ISO 8601 UTC timestamp with three fractional digits at which the row was last mutated. Refreshed on any field write, including writes performed by cascading side effects (for example, when a guest's decline propagates to the wedding's `seating_dirty` flag, the wedding's `updated_at` advances even though no client touched the wedding directly).
- `version` (integer): a counter that starts at 1 on create and increments by exactly 1 on every mutation, whether driven by a direct request or by a cascade. The counter is the substrate of the optimistic concurrency mechanism described in §2.8.

All nine entities in this system maintain the full quartet (`id`, `created_at`, `updated_at`, `version`); there is no entity in this scaffold that carries only `id` and `created_at`.

### 2.5. Nested Resource Retrieval and Path Validation

Many endpoints address a nested resource through a path that contains more than one identifier — for example, a guest-scoped path for adding plus-ones references a parent `Guest`, and the registry-item-scoped purchase ingest references a parent `RegistryItem`. The server validates path identifiers strictly left-to-right and returns `ERR_NOT_FOUND` (HTTP 404) for the **leftmost** identifier that fails to resolve to a live row. A request targeting a guest under a non-existent wedding therefore rejects with `ERR_NOT_FOUND` pointing at the wedding, and the guest existence check is never reached. This applies uniformly to GETs, POSTs, PATCHes, and DELETEs.

### 2.6. Wedding-Scoped Hierarchical Consistency

Every operational entity — `MealOption`, `Table`, `Guest`, `PlusOne`, `SeatingAssignment`, `RegistryItem`, `Purchase`, and `ThankYouNote` — is wedding-scoped, either directly through a `wedding_id` field or transitively through its parent chain. Once a wedding's `status` reaches `ARCHIVED`, every mutation against the wedding itself or against any of its descendants is rejected with `ERR_WEDDING_ARCHIVED` (HTTP 409): no new RSVPs, no new purchases, no new thank-you-note transitions, no new seating edits. Reads continue to function.

Cross-wedding foreign-key references are likewise forbidden. A guest's chosen `meal_option_id` must refer to a `MealOption` whose `wedding_id` matches the guest's own `wedding_id`; a `SeatingAssignment` must reference a `Table` whose `wedding_id` matches the assignment's `wedding_id`; a `ThankYouNote` cascade-created from a `Purchase` carries the wedding of that purchase's `RegistryItem` and may not point at any other wedding. Any payload that violates these constraints is rejected with `ERR_CROSS_WEDDING_REFERENCE` (HTTP 422).

When the system cascades state from a parent to a child (a wedding's archive flowing down into its registry items, a guest's decline flowing down into their plus-one and seating assignment, a purchase's classification flowing into the parent registry item's aggregate quantities), each touched row independently advances its `updated_at` and `version`. There is no batch-write "single tick"; if a single user action mutates three rows by cascade, three `version` counters move.

### 2.7. Precision and Rounding

All quantitative outputs in this system are integers — RSVP counts, table capacities, gift quantities — with one exception: the thank-you completion percentage, which is a number rounded half-up to exactly two decimal places. The rounding order is pinned: aggregate the raw weighted contribution at full numeric precision, divide by the denominator, multiply by 100, and only then round half-up to two decimal places. Rounding each per-note contribution before summation is forbidden because at large note counts the cumulative drift produces a different cent value.

### 2.8. Optimistic Concurrency Control

Two write paths in the system require the caller to declare which parent `version` they last observed; both reject with `ERR_STALE_VERSION` (HTTP 412) when the declared value does not equal the parent's current `version` at the moment of write.

- **Seating finalization against a Wedding.** Finalizing a wedding's seating plan requires a non-optional `expected_wedding_version` field in the request body. The server compares it to the target `Wedding`'s current `version`; on mismatch the request is rejected with `ERR_STALE_VERSION`. The intended scenario is a late RSVP flip (an `ATTENDING` guest dropping to `DECLINED`) whose cascade has already bumped the wedding's `version` and set `seating_dirty` to true between the moment the couple loaded the seating UI and the moment they submitted the finalize: the OCC check ensures the couple cannot lock in a plan they have not actually observed.
- **Duplicate cancellation and promotion against a RegistryItem.** Cancelling or promoting any `Purchase` requires a non-optional `expected_registry_item_version` field in the request body. The server compares it to the parent `RegistryItem`'s current `version`; on mismatch the rejection is again `ERR_STALE_VERSION` (HTTP 412). The intended scenario is a fresh cross-platform purchase ingest landing between the couple's read of the duplicates list and the cancel or promote submit: that ingest bumps the registry item's `version`, so the couple's view of `fulfilled_quantity` and `pending_quantity` is stale, and the decision must be re-made against the fresh totals.

No other endpoint takes a version field. Endpoints not enumerated above do not accept `expected_wedding_version` or `expected_registry_item_version` in their bodies, and supplying one is silently ignored — versioning concurrency is opt-in per endpoint as listed.

### 2.9. Validation Ordering

When multiple validations could fire on the same request, the server evaluates them in a fixed priority order so that error responses are deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED` at 401), then role-based authorization (`ERR_FORBIDDEN` at 403), then existence of every path-templated identifier (`ERR_NOT_FOUND` at 404, leftmost-first per §2.5), then the wedding-archive guard (`ERR_WEDDING_ARCHIVED` at 409), then state-machine preconditions on the target entity (`ERR_INVALID_STATE` at 409). Business-safety rules — the kids-meal pairing rule and the kids-only seating rule — fire next, ahead of plus-one eligibility, ahead of cross-wedding referential checks, ahead of meal-capacity and table-capacity caps, ahead of the seating uniqueness check, ahead of the RSVP-deadline guard for `GuestSelf`, ahead of the idempotent-purchase-ingest check, and ahead of the OCC version-match check. The shape-level `ERR_INVALID_REQUEST` (HTTP 400) — missing required field, malformed enum, integer out of range, empty `drafted_body` — fires last. The relative ordering between rules in the same category matches the order in which they are written into the rule tables in §1.4 of the source specification: kids-meal pairing precedes kids-only seating; plus-one eligibility precedes the cross-wedding check; meal-full precedes table-full; table-full precedes the duplicate-seating uniqueness check.

### 2.10. The Server Clock

Every comparison the system makes against "the current time" — checking that a wedding's `ceremony_at` lies in the future, checking that `rsvp_deadline_at` has not yet been crossed, stamping a thank-you note's `sent_at` — reads a single logical `current_utc` from the server. Production deployments use the wall clock; benchmark deployments expose a test-driving endpoint that allows a `PlatformAdmin` to set `current_utc` directly via a `to_iso8601` payload field. The clock-set endpoint is documented in §4 and is outside the public business surface (its path is prefixed with an underscore for that reason).

## 3. Business Logic & Workflows

### 3.1. Founding the Event: Wedding Lifecycle from Draft to Archive

A wedding enters the system in `DRAFT`. The `Couple` creating it provides a `title` for the event, a `ceremony_at` instant marking when vows will be exchanged, and an `rsvp_deadline_at` instant after which guests can no longer self-RSVP. The server records the operator's `couple_user_id` from the request body — a value that must subsequently match the `X-User-ID` on any further write against this wedding. The system seeds three derived fields on create: `status` is set to `DRAFT`, `seating_dirty` is set to false, and `total_capacity` is set to 0 (no tables yet).

While in `DRAFT` the couple builds out the event's static structure: tables, meal options, guests. Tables are added one at a time, each with a `table_number` that must be unique within the wedding and at least 1, a `capacity` that is at least 1, and an optional `kids_only` flag (defaulting to false). Adding a table refreshes `total_capacity` to the sum of every table's `capacity` and advances the wedding's `version` by 1. Meal options are added with a short `code` (unique within the wedding), a human-readable `label`, an `is_kids` flag (defaulting to false) that marks the option as reserved for guests under the wedding's kids age threshold, and a `max_servings` integer of at least 1 representing the caterer's hard ceiling on how many attendees can select that meal. Guests are added one at a time with `full_name`, `email` (case-insensitively unique within the wedding), an `is_child` flag (defaulting to false), and a `plus_one_allowed` flag (defaulting to false); on create the guest is assigned `rsvp_status` of `INVITED`, the server mints an opaque `invitation_token` used later for `GuestSelf` authentication, and `meal_option_id` is left null.

Opening RSVPs — transitioning `status` from `DRAFT` to `RSVP_OPEN` — requires three preconditions: the wedding's `ceremony_at` must lie strictly after `current_utc`; the wedding's `rsvp_deadline_at` must lie strictly after `current_utc` and strictly before `ceremony_at`; and the wedding must have at least one `MealOption` whose `is_kids` is false (an adult meal must exist before invitations go live). On a successful open, the invitation tokens already minted on guest-create become operative, and the wedding's `version` advances by 1. Each precondition failure is rejected with `ERR_INVALID_STATE` (HTTP 409).

Closing RSVPs — transitioning from `RSVP_OPEN` to `RSVP_CLOSED` — happens in one of two ways: an explicit close request from the `Couple`, or automatically the next time any write hits the wedding after `current_utc` has crossed `rsvp_deadline_at`. The automatic and the explicit close share an identical cascade: every `Guest` still in `INVITED` is auto-transitioned to `DECLINED` with their `meal_option_id` cleared to null; any `PlusOne` under that guest is itself auto-declined with `meal_option_id` cleared; and the wedding's `seating_dirty` flag is recomputed against the current set of `ATTENDING` guests and plus-ones. The wedding's `version` advances by 1 on the transition itself, and each touched guest, plus-one, and assignment touched independently advances its own `version` per §2.6.

Finalizing the seating chart — transitioning from `RSVP_CLOSED` to `SEATED` — requires every `ATTENDING` guest and every `ATTENDING` plus-one to be referenced by exactly one `SeatingAssignment`, no `Table` to be over `capacity`, no `kids_only` table to seat any non-child, and the OCC `expected_wedding_version` to match (see §2.8). A successful finalize clears `seating_dirty` back to false and bumps the wedding's `version` by 1. Any subsequent change that invalidates the seating — deleting a `SeatingAssignment`, an `ATTENDING` guest or plus-one flipping to `DECLINED` while the wedding is in `SEATED` — automatically transitions the wedding back from `SEATED` to `RSVP_CLOSED` and sets `seating_dirty` to true, leaving the couple to re-plan and re-finalize. Re-running the seating algorithm against an already-`SEATED` wedding likewise drops it back to `RSVP_CLOSED` because the prior plan is being replaced.

Archiving — transitioning from `SEATED` to `ARCHIVED` — requires `current_utc` to lie strictly after `ceremony_at`. After archive, every child entity is read-only per §2.6, and every `OPEN` or `FULFILLED` `RegistryItem` of this wedding automatically transitions to `ARCHIVED` as well; that cascade bumps each registry item's `version` independently.

### 3.2. Guest and Plus-One RSVPs

While the wedding is in `RSVP_OPEN` and `current_utc` is still before `rsvp_deadline_at`, an invited guest may RSVP themselves through their `invitation_token`, or the couple may RSVP on their behalf. The RSVP payload carries an `attending` boolean and an optional `meal_option_id`. An `attending=true` RSVP transitions the guest's `rsvp_status` from `INVITED` to `ATTENDING`, stores the supplied `meal_option_id` on the guest, and is subject to three independent gates: the meal must belong to this wedding (otherwise `ERR_CROSS_WEDDING_REFERENCE`); the meal's `is_kids` flag must equal the guest's `is_child` flag — children may pick only kids meals and adults may pick only adult meals (otherwise `ERR_KIDS_MEAL_PAIRING`); and accepting the RSVP must not push the running count of `ATTENDING` guests-plus-plus-ones who have chosen that same meal above the meal's `max_servings` cap (otherwise `ERR_MEAL_FULL`). When a `GuestSelf` is the caller, an additional temporal check applies: even if the wedding is still nominally `RSVP_OPEN`, a `GuestSelf` RSVP submitted at or after `rsvp_deadline_at` is rejected with `ERR_RSVP_DEADLINE_PASSED` (HTTP 409). The `Couple` is not subject to that deadline check; they may RSVP a guest by proxy after the deadline up until the close transition fires.

An `attending=false` RSVP transitions the guest to `DECLINED`, sets `meal_option_id` to null, and cascades downward: every `PlusOne` under that guest is itself auto-declined with `meal_option_id` cleared, and if the wedding was already `SEATED`, any `SeatingAssignment` whose `assignee_type` is `GUEST` and `assignee_id` is this guest is deleted, along with any assignment for any plus-one of this guest, and the wedding is reverted to `RSVP_CLOSED` with `seating_dirty=true`. This is the maximum-depth cascade in the system: decline a guest while the wedding is `SEATED`, and three layers of state move — the plus-one's `rsvp_status`, the seating assignments belonging to both, and the wedding's posture.

Decline of a guest already in `ATTENDING` is permitted across `RSVP_OPEN`, `RSVP_CLOSED`, and `SEATED`. Decline of a guest still in `INVITED` is permitted in `RSVP_OPEN` and `RSVP_CLOSED` (where it is the same operation the close cascade applies). The couple may also reverse direction — taking a guest back from `ATTENDING` or `DECLINED` to `INVITED` — but only while the wedding is still `RSVP_OPEN` and `current_utc` is still before `rsvp_deadline_at`. The revoke from `ATTENDING` to `INVITED` clears `meal_option_id` back to null and is rejected if any `PlusOne` under the guest currently sits in `ATTENDING`; the couple must delete that `PlusOne` first. The revoke from `DECLINED` to `INVITED` has no further side effects.

Adding a plus-one is a couple-only operation, scoped under the guest the plus-one accompanies. The system enforces a one-shot rule via the priority-ordered checks of §2.9: the parent guest's `plus_one_allowed` must currently be true, and the guest must not already have a `PlusOne`; either violation is rejected with `ERR_PLUS_ONE_NOT_ALLOWED` (HTTP 422). The same error fires if the couple attempts to flip `plus_one_allowed` from true to false on a guest who already has a plus-one. A plus-one carries its own `full_name` and `is_child`, optionally accepts a `meal_option_id` on create, and starts in `rsvp_status` of `ATTENDING`. A plus-one may subsequently RSVP — either through `GuestSelf` (the parent guest's invitation token authenticates the plus-one too) or through the couple — with the same `attending` and optional `meal_option_id` payload as a guest. An `attending=false` plus-one RSVP transitions the plus-one to `DECLINED`, clears `meal_option_id`, deletes any `SeatingAssignment` referencing this plus-one (with `assignee_type` of `PLUS_ONE` and `assignee_id` equal to the plus-one's `id`), and, if the wedding was `SEATED`, drops it back to `RSVP_CLOSED` with `seating_dirty=true`. A plus-one may also be deleted outright by the couple, which performs the same seating-assignment cleanup and `seating_dirty` flip but removes the row entirely.

Both guest and plus-one RSVP endpoints share the same payload shape — `attending` plus optional `meal_option_id` — and the same kids-meal pairing and meal-full gates apply on either path; on the plus-one path the `is_child` field consulted is the plus-one's own.

### 3.3. Building the Seating Chart

A `SeatingAssignment` records the placement of one attendee — either a `Guest` or a `PlusOne` — at one `Table`. The discriminator field `assignee_type` is the enum value `GUEST` or `PLUS_ONE`; the `assignee_id` is the referenced entity's `id`. Creating an assignment manually requires the couple to supply `wedding_id`, `table_id`, `assignee_type`, and `assignee_id`; the system enforces three independent constraints in priority order. First, the kids-only seating rule: a `Table` with `kids_only=true` admits only assignees whose `is_child` is true, and conversely an assignee with `is_child=true` may only be seated at a non-`kids_only` table when every `kids_only` table of this wedding is at full `capacity` — kids spill into adult tables only when no kids-only slot remains. A violation is rejected with `ERR_KIDS_SEATING_VIOLATION` (HTTP 422). Second, the table-capacity ceiling: an assignment that would push the count of existing assignments on the target `Table` above its `capacity` is rejected with `ERR_TABLE_FULL` (HTTP 422). Third, the per-attendee uniqueness check: the triple of `wedding_id`, `assignee_type`, and `assignee_id` is enforced as unique across `SeatingAssignment` rows — an attempt to seat a guest already seated is rejected with `ERR_ALREADY_SEATED` (HTTP 422). Cross-wedding integrity (the assignment's `wedding_id` and the table's `wedding_id` must match) is checked at priority §2.9 ahead of the capacity and uniqueness checks and surfaces as `ERR_CROSS_WEDDING_REFERENCE`. Creating an assignment against a wedding already in `SEATED` automatically drops it back to `RSVP_CLOSED` with `seating_dirty=true` because the prior plan is being amended.

Deleting a `SeatingAssignment` is the inverse: any wedding in `SEATED` is dropped back to `RSVP_CLOSED` with `seating_dirty=true` and its `version` advances by 1.

The couple may also ask the server to compute a seating chart in one shot through the auto-seat operation, which has two variants distinguished by HTTP method. The dry-run variant — a read-style call — returns the plan and the unseatable list without persisting anything and without touching `seating_dirty`. The committing variant — a write-style call — requires the wedding's `status` to be either `RSVP_CLOSED` or `SEATED` (a `DRAFT` or `RSVP_OPEN` wedding has nothing finalize-worthy to plan against and is rejected with `ERR_INVALID_STATE`); it atomically deletes every existing `SeatingAssignment` for the wedding and recreates rows from the freshly computed plan; on commit, the wedding's `version` advances by 1 and `seating_dirty` is left set to true so the couple still has to explicitly finalize. If the wedding was `SEATED` when commit is invoked, it auto-transitions back to `RSVP_CLOSED` because the seating is being replaced.

The auto-seat algorithm is a deterministic waterfall allocation, structured as follows. The attendee list is the concatenation of all `Guest` rows of this wedding whose `rsvp_status` is `ATTENDING` followed by all `PlusOne` rows of this wedding whose `rsvp_status` is `ATTENDING`, sorted by `created_at` ascending as the primary key and `full_name` ascending as the disciplined tie-break (the `id` is never used as a tie-break). The table list is every `Table` of this wedding sorted by `table_number` ascending. The algorithm walks the attendee list in order and, for each attendee, scans the table list in order to find the first table where three conditions all hold: the table's current assignment count is strictly less than its `capacity`; if the table has `kids_only=true`, the attendee's `is_child` must be true; and if the table has `kids_only=false`, the attendee's `is_child` must be false unless that attendee's `is_child` is true and every `kids_only=true` table in this wedding is already full, in which case the child is permitted to overflow into the non-kids-only table. The attendee is placed at the first table satisfying these predicates; if no table satisfies them, the attendee is appended to the unseatable list with a reason and the algorithm continues with the next attendee. The output is an object with two arrays: `plan`, whose elements carry `assignee_type`, `assignee_id`, `table_id`, and `table_number`; and `unseatable`, whose elements carry `assignee_type`, `assignee_id`, and a reason.

### 3.4. Meal Aggregation and Reporting

Whenever a guest's `rsvp_status` flips between `ATTENDING` and `DECLINED`, or whenever a plus-one does likewise, or whenever a couple changes a `meal_option_id` on an already-`ATTENDING` guest or plus-one, the server recomputes per-meal attendance counts. For each `MealOption` of the wedding, the count is the number of `Guest` rows belonging to that wedding whose `rsvp_status` is `ATTENDING` and whose `meal_option_id` equals that meal's `id`, plus the number of `PlusOne` rows under the same condition. `INVITED` rows are excluded; `DECLINED` rows are excluded; rows where `meal_option_id` is null are excluded. The same count is what the `max_servings` cap is enforced against: a request that would, after the change, raise count(M) above M.`max_servings` is rejected with `ERR_MEAL_FULL` (HTTP 422). Boundary inclusivity matters here — the cap is inclusive, so a count exactly equal to `max_servings` is permitted; only a count strictly greater than `max_servings` is rejected.

The meal summary endpoint surfaces these counts to the couple. Its response carries an `items` array — one element per `MealOption`, each carrying `meal_option_id`, `code`, `label`, `is_kids`, `max_servings`, and `count` — and a `total_attendees` integer (the sum of all per-meal counts, equal to the total number of `ATTENDING` guests plus `ATTENDING` plus-ones who have selected a meal).

### 3.5. Cross-Platform Purchase Ingest and Duplicate Cancellation

The gift registry holds `RegistryItem` rows, each with a couple-defined `sku` (unique within the wedding), a `title`, a `target_quantity` of at least 1, a `unit_price_cents` of at least 0 used only for display, an aggregate `status` (`OPEN`, `FULFILLED`, or `ARCHIVED`), and two derived integer counters: `fulfilled_quantity` and `pending_quantity`. The status starts at `OPEN`; the counters both start at 0.

Purchases flow into the system from external commerce platforms (and occasionally from a manual entry surface). Each `Purchase` carries a `platform_code` identifying its source platform (for example `STORE_A`, `STORE_B`, or `MANUAL`), an `external_purchase_id` minted by that platform, a `purchaser_name` reporting the gift-giver as the platform sees them, an integer `quantity` of at least 1, and an `occurred_at` ISO 8601 UTC timestamp at which the platform recorded the purchase. The pair of `platform_code` and `external_purchase_id` is globally unique: a re-ingest of an already-recorded pair is idempotent, returning the existing row's `id` with HTTP 200 and without mutating any aggregate counters. The narrow exception is when the same key arrives with a **different** `quantity`: that is treated as a true conflict and rejected with `ERR_DUPLICATE_EXTERNAL_PURCHASE` (HTTP 409).

A successful ingest classifies the new purchase by replaying every `Purchase` row whose `registry_item_id` points at the same parent `RegistryItem`. The replay is sorted by `occurred_at` ascending as the primary key and by each row's `created_at` ascending as the deterministic tie-break (the `id` is never used as a tie-break). The classifier maintains a running confirmed total, starting at zero. Each purchase in the chronological order is examined in turn: a purchase whose current `status` is `CANCELLED` contributes nothing and is skipped; an existing row whose current `status` is the authoritative current state and contributes its `quantity` to the running total only if that status is `CONFIRMED`; and for the freshly ingested row itself, the classifier computes the tentative running total it would produce — that is, the running confirmed total before this row, plus this row's `quantity`. If the tentative running total is less than or equal to the parent `RegistryItem`'s `target_quantity`, the new row is classified `CONFIRMED` and the running total advances to the tentative value. If the tentative running total is strictly greater than `target_quantity` — the boundary is inclusive, so hitting `target_quantity` exactly still confirms — the new row is classified `PENDING_REVIEW` and its `dup_of_purchase_id` is set to the `id` of the earliest `CONFIRMED` purchase such that the cumulative running confirmed total was less than or equal to `target_quantity` before that purchase and strictly greater after it: the canonical purchase that "ate the last slot". On a `CONFIRMED` purchase the `dup_of_purchase_id` is always null.

After replay, the parent `RegistryItem`'s `fulfilled_quantity` is recomputed as the sum of `quantity` across all `CONFIRMED` rows, and `pending_quantity` as the sum of `quantity` across all `PENDING_REVIEW` rows. The registry item's `version` advances by 1. If `fulfilled_quantity` is greater than or equal to `target_quantity`, the registry item's `status` transitions automatically from `OPEN` to `FULFILLED`; otherwise it stays `OPEN`. A wedding that has reached `ARCHIVED` freezes its registry items in `ARCHIVED` per §3.1 regardless of the purchase totals. The `RegistryItem` must currently be `OPEN` at the moment of ingest; ingesting against a `FULFILLED` or `ARCHIVED` item is rejected with `ERR_INVALID_STATE` (note that an `OPEN` item that becomes `FULFILLED` as a result of this very purchase is permitted — the precondition is checked at ingest time, before the cascade).

When a purchase lands in `CONFIRMED` — whether on initial ingest or by later promotion — the system auto-creates one `ThankYouNote` whose `purchase_id` is the new purchase's `id`, whose `wedding_id` is denormalized from the parent registry item's `wedding_id`, whose `status` is `PENDING`, whose `drafted_body` is null, and whose `sent_at` is null. A purchase that lands in `PENDING_REVIEW` does not get a thank-you note yet — the duplicates queue is the couple's review surface and a thank-you would be premature.

The couple resolves duplicates one of two ways. To cancel, the couple submits the duplicate cancellation; the purchase's `status` transitions from `PENDING_REVIEW` to `CANCELLED` (or directly from `CONFIRMED` to `CANCELLED` if the couple is cancelling the canonical row instead). On the `PENDING_REVIEW` to `CANCELLED` path, the parent's `pending_quantity` decreases by this purchase's `quantity` and the registry item's `version` advances by 1; the cascade hard-deletes any `ThankYouNote` previously created against this purchase (in the normal flow there is none, because `CONFIRMED` never fired for this row, so the cascade is a no-op). On the `CONFIRMED` to `CANCELLED` path, the parent's `fulfilled_quantity` decreases by this purchase's `quantity`, the registry item's `version` advances by 1, any `ThankYouNote` on this purchase is hard-deleted, and if the registry item was previously `FULFILLED` and the new `fulfilled_quantity` drops below `target_quantity`, the registry item reverts from `FULFILLED` to `OPEN`. The cancel write requires `expected_registry_item_version` in the request body per §2.8, and an `ERR_INVALID_STATE` is returned if the purchase is already `CANCELLED`.

To promote a duplicate — when the couple accepts a "duplicate" as a legitimately desired extra — the couple submits the promotion. The purchase transitions from `PENDING_REVIEW` to `CONFIRMED`; the parent `RegistryItem` must currently be `OPEN`. The parent's `pending_quantity` decreases by this purchase's `quantity`, `fulfilled_quantity` increases by this purchase's `quantity`, and the registry item's `version` advances by 1. If the new `fulfilled_quantity` reaches or exceeds `target_quantity`, the registry item's `status` flips from `OPEN` to `FULFILLED`. A `ThankYouNote` with `status` of `PENDING` is auto-created for this newly confirmed purchase. The promote write also requires `expected_registry_item_version` per §2.8.

Two distinct read surfaces show registry data. The settled view — a plain read on the registry item — surfaces `fulfilled_quantity` but does not surface `pending_quantity`. The provisional view — the per-item purchase list with the `include_pending` query parameter set to true — surfaces every `PENDING_REVIEW` row alongside the `CONFIRMED` ones so the couple can review the duplicates queue before deciding; `fulfilled_quantity` continues to reflect `CONFIRMED` only, and `pending_quantity` is surfaced as a separate counter. The two views diverge for any registry item with a non-zero `pending_quantity`, and the divergence is intentional.

### 3.6. Thank-You Tracking and Completion Scoring

A `ThankYouNote` progresses through three states: `PENDING` (auto-created when its parent `Purchase` reaches `CONFIRMED`), `DRAFTED` (the couple has saved body text but not yet sent), and `SENT` (the couple has marked the note dispatched). Each ThankYouNote carries its `purchase_id`, the denormalized `wedding_id` it belongs to (so the list endpoint can filter cheaply without joining through the purchase chain), the current `status`, the saved `drafted_body` text, and the `sent_at` timestamp.

To draft a note, the couple supplies a non-empty `drafted_body` and the note transitions from `PENDING` to `DRAFTED`; the body text is stored, and the parent `Purchase` must currently be in `CONFIRMED` (otherwise `ERR_INVALID_STATE`). An empty `drafted_body` is rejected at shape level with `ERR_INVALID_REQUEST` (HTTP 400). To send a note, the couple invokes the send transition; the note moves from `DRAFTED` to `SENT`, the server stamps `sent_at` with the current `current_utc`, and the same parent-purchase-in-`CONFIRMED` precondition applies. If a parent `Purchase` is cancelled and its `ThankYouNote` had previously been created, that note is hard-deleted as part of the cancel cascade (§3.5) — there is no soft-delete state for orphaned thank-yous.

The thank-you completion report surfaces a weighted progress score across all thank-you notes attached to `CONFIRMED` purchases of this wedding. The inputs are four integer counts: `n_total`, the total number of such thank-you notes; `n_sent`, the count of those whose `status` is `SENT`; `n_drafted`, the count whose `status` is `DRAFTED`; and `n_pending`, the count whose `status` is `PENDING`. The weights are pinned: a `SENT` note counts for 1.00, a `DRAFTED` note counts for 0.40, and a `PENDING` note counts for 0.00. The raw weighted sum is the number of sent notes times 1.00, plus the number of drafted notes times 0.40, plus the number of pending notes times 0.00 (the last term contributes nothing but is named explicitly so a future weight change is obvious). The completion percentage `completion_pct`, when `n_total` is greater than zero, is the raw weighted sum divided by `n_total`, multiplied by 100, and then rounded half-up to exactly two decimal places (the rounding-order pin from §2.7 applies: aggregate at full precision, divide, multiply, and round only once at the end). When `n_total` is zero — a wedding with no confirmed purchases yet — `completion_pct` is exactly 100.00, on the principle that an empty registry is trivially complete. The boundary flag `is_complete` is true if and only if `n_sent` equals `n_total` and `n_total` is strictly greater than zero. Thank-you notes that have been hard-deleted by a purchase cancellation cascade are excluded from all four counts.

## 4. Endpoint Definitions

This section enumerates every endpoint the system exposes. Resource creations return HTTP 201 with the created resource in the `data` field; resource modifications (including state transitions) return HTTP 200 with the updated resource; deletes return HTTP 204 with no body. Error responses return their declared HTTP status with the standard error envelope per §2.2. Endpoint paths whose first segment is the underscore-prefixed `_clock` are outside the public business surface and intended for test orchestration only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/weddings` | Create a wedding in `DRAFT`. | `Couple` |
| GET | `/weddings/{id}` | Read a wedding. | `Couple`, `PlatformAdmin` |
| GET | `/weddings` | List weddings, filterable by `couple_user_id`. | `Couple`, `PlatformAdmin` |
| POST | `/weddings/{id}/open-rsvp` | Transition `DRAFT` → `RSVP_OPEN`. | `Couple` |
| POST | `/weddings/{id}/close-rsvp` | Transition `RSVP_OPEN` → `RSVP_CLOSED`. | `Couple` |
| POST | `/weddings/{id}/finalize-seating` | Transition `RSVP_CLOSED` → `SEATED`; OCC-guarded. | `Couple` |
| POST | `/weddings/{id}/archive` | Transition `SEATED` → `ARCHIVED`. | `Couple`, `PlatformAdmin` |
| GET | `/weddings/{id}/meal-summary` | Per-meal attendance summary. | `Couple`, `PlatformAdmin` |
| GET | `/weddings/{id}/auto-seat` | Dry-run seating chart. | `Couple` |
| POST | `/weddings/{id}/auto-seat` | Run seating chart and persist. | `Couple` |
| GET | `/weddings/{id}/thank-you-report` | Thank-you completion score. | `Couple` |
| POST | `/weddings/{id}/meal-options` | Add a meal option. | `Couple` |
| GET | `/weddings/{id}/meal-options` | List meal options of a wedding. | `Couple`, `GuestSelf`, `PlatformAdmin` |
| GET | `/meal-options/{id}` | Read a meal option. | `Couple`, `GuestSelf`, `PlatformAdmin` |
| POST | `/weddings/{id}/tables` | Add a table. | `Couple` |
| GET | `/weddings/{id}/tables` | List tables of a wedding. | `Couple`, `PlatformAdmin` |
| GET | `/tables/{id}` | Read a table. | `Couple`, `PlatformAdmin` |
| POST | `/weddings/{id}/guests` | Add a guest; mints `invitation_token`. | `Couple` |
| GET | `/weddings/{id}/guests` | List guests of a wedding (filter by `rsvp_status`). | `Couple`, `PlatformAdmin` |
| GET | `/guests` | List guests across weddings (filter by `meal_option_id`, `rsvp_status`). | `Couple`, `PlatformAdmin` |
| GET | `/guests/{id}` | Read a guest. | `Couple`, `GuestSelf`, `PlatformAdmin` |
| POST | `/guests/{id}/rsvp` | Set guest RSVP (`attending` + optional `meal_option_id`). | `Couple`, `GuestSelf` |
| POST | `/guests/{id}/revoke-rsvp` | Revert guest to `INVITED`. | `Couple` |
| POST | `/guests/{id}/plus-ones` | Add the single plus-one for a guest. | `Couple` |
| GET | `/guests/{id}/plus-ones` | List plus-ones under a guest. | `Couple`, `GuestSelf`, `PlatformAdmin` |
| GET | `/plus-ones` | List plus-ones (filter by `wedding_id`, `meal_option_id`). | `Couple`, `PlatformAdmin` |
| GET | `/plus-ones/{id}` | Read a plus-one. | `Couple`, `GuestSelf`, `PlatformAdmin` |
| POST | `/plus-ones/{id}/rsvp` | Set plus-one RSVP (`attending` + optional `meal_option_id`). | `Couple`, `GuestSelf` |
| DELETE | `/plus-ones/{id}` | Remove a plus-one. | `Couple` |
| POST | `/seating-assignments` | Create a single seating assignment. | `Couple` |
| GET | `/seating-assignments` | List seating assignments (filter by `wedding_id`, `table_id`, `assignee_type`, `assignee_id`). | `Couple`, `PlatformAdmin` |
| GET | `/seating-assignments/{id}` | Read a seating assignment. | `Couple`, `PlatformAdmin` |
| DELETE | `/seating-assignments/{id}` | Remove a seating assignment. | `Couple` |
| POST | `/weddings/{id}/registry-items` | Add a registry item. | `Couple` |
| GET | `/weddings/{id}/registry-items` | List registry items of a wedding (filter by `status`). | `Couple`, `PlatformIntegration`, `PlatformAdmin` |
| GET | `/registry-items/{id}` | Read a registry item (settled view). | `Couple`, `PlatformIntegration`, `PlatformAdmin` |
| POST | `/registry-items/{id}/purchases` | Ingest a cross-platform purchase; idempotent on (`platform_code`, `external_purchase_id`). | `PlatformIntegration`, `Couple` |
| GET | `/registry-items/{id}/purchases` | List purchases of a registry item (filter by `include_pending`, `status`). | `Couple`, `PlatformIntegration`, `PlatformAdmin` |
| GET | `/purchases/{id}` | Read a purchase. | `Couple`, `PlatformIntegration`, `PlatformAdmin` |
| GET | `/purchases` | List purchases (filter by `dup_of_purchase_id`, `status`). | `Couple`, `PlatformIntegration`, `PlatformAdmin` |
| POST | `/purchases/{id}/cancel-duplicate` | Cancel a purchase; OCC-guarded by `expected_registry_item_version`. | `Couple` |
| POST | `/purchases/{id}/promote` | Promote `PENDING_REVIEW` to `CONFIRMED`; OCC-guarded. | `Couple` |
| GET | `/thank-you-notes` | List thank-you notes (filter by `wedding_id`, `purchase_id`, `status`). | `Couple`, `PlatformAdmin` |
| GET | `/thank-you-notes/{id}` | Read a thank-you note. | `Couple`, `PlatformAdmin` |
| POST | `/thank-you-notes/{id}/draft` | Save `drafted_body` and transition to `DRAFTED`. | `Couple` |
| POST | `/thank-you-notes/{id}/send` | Transition `DRAFTED` → `SENT`; stamps `sent_at`. | `Couple` |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's `current_utc` to a supplied `to_iso8601` instant. | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_WEDDING_ARCHIVED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_KIDS_MEAL_PAIRING` | 422 |
| `ERR_KIDS_SEATING_VIOLATION` | 422 |
| `ERR_PLUS_ONE_NOT_ALLOWED` | 422 |
| `ERR_CROSS_WEDDING_REFERENCE` | 422 |
| `ERR_MEAL_FULL` | 422 |
| `ERR_TABLE_FULL` | 422 |
| `ERR_ALREADY_SEATED` | 422 |
| `ERR_RSVP_DEADLINE_PASSED` | 409 |
| `ERR_DUPLICATE_EXTERNAL_PURCHASE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
