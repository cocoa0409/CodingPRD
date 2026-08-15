# Clothing Closet API — Product Requirements Document

## 1. Introduction

A community clothing closet operates on a delicate balance: donations arrive in unsorted batches, volunteers work in short scheduled shifts, storage space is finite and season-sensitive, and every client visit must be fair — generous enough to matter, bounded enough that the inventory serves the whole neighborhood. This document specifies the Clothing Closet & Free Store Program API, the operational backbone that tracks a garment from the moment it is donated to the moment it leaves on a client's shoulder — or, when it cannot be sold or given away, into a textile recycling channel that returns a modest credit to the program.

The system governs donation intake and sorting quality standards, client eligibility with visit-frequency and item limits, storage zones with seasonal rotation, volunteer shift scheduling with a staffed-sorting requirement, a referral-partner voucher program with monthly quotas and carryover, special merchandise drives (interview attire, winter coats) with their own bonus pools, and impact reporting built on inventory turnover. All operations are mounted under the `/closet` prefix and are evaluated against a server-owned logical clock so that time-sensitive rules — cooldowns, quotas, drive windows, rotation windows — behave deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to declare the operational capacity in which they act. The system recognizes five roles, spelled exactly as follows: `ProgramAdmin`, `VolunteerLead`, `Volunteer`, `Client`, and `ReferralPartner`. A request whose headers are missing, or whose role value is not one of these five, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not listed among the roles permitted for the target endpoint is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `closed_by_user_id` on a donation batch, as `sealed_by_user_id` or `picked_up_by_user_id` on a recycling batch — but never compares it to any entity's `id`. When `X-User-Role` is `VolunteerLead` or `Volunteer`, `X-User-ID` is the `id` of the acting Volunteer, and ownership checks on any resource that references a Volunteer compare the resource's foreign-key field (such as a signup's `volunteer_id`) to `X-User-ID`. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting Client, and ownership checks compare against client-referencing fields; a Client may read only their own record, their own visits, and their own vouchers. When `X-User-Role` is `ReferralPartner`, `X-User-ID` is the `id` of the acting ReferralPartner, and the partner may read only its own record and issue or revoke vouchers under its own partner id. Any attempt by an entity-backed role to act outside its ownership scope is rejected with `ERR_FORBIDDEN`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Lazy Status Advancement

Every timestamp the server writes — check-ins, checkouts, grading events, stock movements, voucher issuance — is taken from a server-owned logical clock, never from the wall clock. Before any clock call has been made, the logical clock stands at 2026-08-01T00:00:00Z. A `ProgramAdmin` may advance the clock through an admin-only capability that accepts a target instant `to_iso8601` and answers with the resulting `current_utc`; once advanced, the clock never falls back to wall-clock time.

Two resource families advance their status lazily against this clock rather than through a background scheduler. A voucher whose expiry has been reached flips from `ISSUED` to `EXPIRED` the next time it is read or listed, and the same evaluation happens on any redemption attempt. A special drive moves from `UPCOMING` to `ACTIVE` when the clock stands within its window, and from `ACTIVE` to `CLOSED` once the window has passed; these advancements occur whenever the drive is read and whenever a check-in evaluates the drive pools available to a visit.

### 2.5. Common Resource Properties

Every resource in the system — clients, visits, distribution lines, donation batches, items, storage zones, volunteers, shifts, signups, referral partners, vouchers, drives, rotations, and recycling batches — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification; it refreshes on every change to the resource.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource, including status transitions and server-side cascades that touch the record.

This convention provides a consistent audit trail and unique addressability for every entity in the system.

### 2.6. Request Validation Order and Nested Path Resolution

When several rules could reject the same request, the server evaluates them in a fixed order and surfaces only the earliest failure. The cascade runs as follows: first, header presence and role recognition (`ERR_UNAUTHENTICATED`); second, role authorization on the endpoint (`ERR_FORBIDDEN`); third, ownership scoping for entity-backed roles (`ERR_FORBIDDEN`); fourth, existence of every referenced identifier (`ERR_NOT_FOUND`); fifth, request shape — required fields present, types and enum values valid, numeric ranges satisfied (`ERR_INVALID_REQUEST`); sixth, optimistic-concurrency version agreement (`ERR_STALE_VERSION`); seventh, state permissibility of the target resource (`ERR_INVALID_STATE` and the state-flavored business errors); and finally the temporal, capacity, quota, referential, and segregation-of-duties rules described throughout §3. Because existence is checked before body shape, a request targeting a missing resource reports `ERR_NOT_FOUND` even if its payload is also malformed.

For endpoints whose path contains multiple identifiers — for example, a signup addressed by both a shift's `id` and the signup's own `sid` — identifiers are resolved strictly left to right. The request is rejected with `ERR_NOT_FOUND` for the first path identifier that does not resolve, and body-referenced identifiers are validated after the path has been fully resolved.

### 2.7. Optimistic Concurrency Control

Two write operations carry mandatory optimistic concurrency control, and both reject a stale writer with `ERR_STALE_VERSION` (HTTP 412).

Updating a client profile requires the request to carry `expected_client_version`, holding the client's `version` as the writer last observed it. Because a visit's allowance snapshot is taken from the live profile at check-in, a writer who read the profile before another writer's update must not silently overwrite it; if the supplied value no longer matches the client's current `version`, the update is rejected with `ERR_STALE_VERSION` and the stale writer re-reads and retries.

Updating a storage zone likewise requires `expected_zone_version`. Capacity changes interact with live stock counts and with the rotation placement selector, so a writer holding a stale zone snapshot must re-read before reapplying; a mismatch with the zone's current `version` is rejected with `ERR_STALE_VERSION`. Endpoints other than these two updates do not accept a version field.

### 2.8. Zone Occupancy, Posture, and Season Compatibility

A storage zone's `current_stock` counts the items physically assigned to it — those whose `storage_zone_id` names the zone and whose status is `STOCKED` or `RESERVED`. Reserving an item for a visit does not change `current_stock`; the item is still on the shelf until it is distributed.

From `current_stock` and `capacity_items` the server derives the zone's `posture`. When `current_stock` has reached `capacity_items`, the posture is `FULL`, and a zone that is `FULL` refuses any further stocking — the boundary is inclusive, so a zone holding exactly its capacity rejects the next item with `ERR_ZONE_FULL`. Below that, when `current_stock` is at least the result of multiplying `capacity_items` by 0.8 and rounding up to a whole number, the posture is `NEAR_FULL`. Otherwise the posture is `AVAILABLE`. Posture is recomputed on every event that moves stock: stocking, distribution, return, quarantine, restock, rotation movement, and capacity updates.

Season compatibility governs which items a zone may hold. An item whose `season` is `ALL_SEASON` is compatible with every zone; a zone whose `season_policy` is `ALL_SEASON` accepts every item; otherwise the item's `season` must equal the zone's `season_policy`. A stocking attempt that breaks this rule is rejected with `ERR_SEASON_INCOMPATIBLE`.

### 2.9. Weights, Credits, and Numeric Precision

Estimated textile weights are kept at two decimal places of kilograms. Recycling credits are integer cent amounts; every credit computation rounds half up to a whole cent. Allowance arithmetic produces whole items, with the hardship multiplier applied using round-half-up to the nearest integer. Inventory turnover ratios are reported at four decimal places, rounded half up. Timestamp comparisons for visit-frequency rules operate at second precision.

## 3. Business Logic & Workflows

### 3.1. Client Registration, Eligibility, and Discipline

A staff member registers a client by supplying the client's `full_name` and `household_size` — the count of people in the household, which must be at least 1 — and optionally an `eligibility_tier` of `STANDARD` or `HARDSHIP`, defaulting to `STANDARD` when omitted. New clients begin with status `ACTIVE`. Until a client's first checkout, `last_checkout_at` is null. Two rolling counters are maintained on the client record: `visits_in_30d`, the number of the client's own visits that reached `CHECKED_OUT` with a `checked_out_at` inside the trailing 30 days, and `items_in_30d`, the number of lines in `DISTRIBUTED` status on those in-window visits. The window is half-open: a checkout that occurred exactly 30 days (30 full 24-hour periods) before the present instant is excluded. Both counters are recomputed whenever they are read and whenever a check-in, line addition, checkout, or return occurs.

A `VolunteerLead` or `ProgramAdmin` may update a client's `household_size` or `eligibility_tier`; the update follows the optimistic-concurrency rule of §2.7 and increments the client's `version` by one. Discipline is handled through two transitions: suspending moves an `ACTIVE` client to `SUSPENDED`, and reinstating returns a `SUSPENDED` client to `ACTIVE`; each requires the matching current state (otherwise `ERR_INVALID_STATE`) and each increments `version`. A `SUSPENDED` client cannot be checked in for a new visit and cannot be named as the recipient of a newly issued voucher — both attempts fail with `ERR_CLIENT_NOT_ACTIVE` — while a visit already `CHECKED_IN` when the suspension lands is unaffected and may finish normally.

### 3.2. The Shopping Visit: Check-in Through Checkout

A visit begins when a staff member checks a client in, optionally presenting a `voucher_id` to redeem a voucher on the visit. The new visit record references the visiting client through `client_id`, opens in `CHECKED_IN` status, and stamps `checked_in_at` from the logical clock; `checked_out_at` remains null until checkout.

Check-in enforces its rules in a fixed order. The client must be `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`). Then the frequency gate: at least 14 full days must have elapsed since the client's `last_checkout_at` — the boundary is inclusive, so a client whose last checkout was exactly 14 days earlier may check in — and a first-ever visit passes this arm automatically; failure is `ERR_VISIT_COOLDOWN_ACTIVE`. Next, the rolling visit cap: the client's `visits_in_30d` must be fewer than 3, or the check-in fails with `ERR_VISIT_LIMIT_REACHED`. When a voucher is presented, four further checks follow in order: the voucher must not have reached its `expires_at` (at or after expiry the voucher flips to `EXPIRED` and the attempt fails with `ERR_VOUCHER_EXPIRED`); the voucher must still be `ISSUED` (`ERR_VOUCHER_NOT_REDEEMABLE`); the voucher's `client_id` must name the client being checked in (`ERR_VOUCHER_CLIENT_MISMATCH`); and the voucher's issuing partner must be `ACTIVE` (`ERR_PARTNER_SUSPENDED`).

A voucher whose `waives_frequency` flag is true overrides only the 14-day cooldown; the 30-day visit cap and the item caps are never waived. On successful redemption the voucher moves from `ISSUED` to `REDEEMED`, its `redeemed_at` is stamped, and the visit records the redemption in its own `voucher_id` field.

Check-in also snapshots the visit's shopping allowance into `general_allowance`. The base allowance is 8 items, plus 2 additional items for each household member beyond the first, capped at 16 items. For a client in the `HARDSHIP` tier, that capped base is then multiplied by 1.5 and rounded half up to a whole number of items. When a voucher is redeemed on the visit, its `bonus_items` are added on top — the amount folded in is recorded as `voucher_bonus_applied` (0 when no voucher is redeemed) — and the final `general_allowance` is the smaller of that sum and the hard ceiling of 24 items per visit. Drive pools sit outside this arithmetic entirely, as §3.8 describes.

Checkout finalizes a visit. The visit must be `CHECKED_IN` (otherwise `ERR_INVALID_STATE`) and must hold at least one `ACTIVE` line (otherwise `ERR_EMPTY_VISIT_CHECKOUT`). On checkout every `ACTIVE` line becomes `DISTRIBUTED`, and each reserved item moves from `RESERVED` to `DISTRIBUTED`: the item's `distributed_at` is stamped, the zone it left is remembered in `distributed_from_zone_id`, its `storage_zone_id` and `reserved_visit_id` are cleared, the zone's `current_stock` is decremented, and the zone's `posture` is recomputed. The visit stamps `checked_out_at`, the client's `last_checkout_at` is set to the same instant, and the client's rolling counters are recomputed.

A `VolunteerLead` or `ProgramAdmin` may instead void a visit that is still `CHECKED_IN`, moving it to `VOIDED`. Every `ACTIVE` line on the visit becomes `RELEASED`, and each item those lines held returns from `RESERVED` to `STOCKED` with its `reserved_visit_id` cleared. A voucher redeemed on a voided visit stays `REDEEMED`; there is no un-redemption.

### 3.3. Distribution Lines, Limits, and Returns

Adding a line to a visit is the act of reserving a shelf item for the shopper. The request names an `item_id`; the visit must be `CHECKED_IN` and the item must be `STOCKED`, or the attempt fails with `ERR_ITEM_NOT_AVAILABLE`. On success the item moves from `STOCKED` to `RESERVED`, its `reserved_visit_id` points at the visit, and the new line begins in `ACTIVE` status with `visit_id` naming its owning visit. The line copies the item's `category` into `category_snapshot` at creation — one of `ADULT_TOPS`, `ADULT_BOTTOMS`, `CHILDRENS`, `COATS`, `INTERVIEW_ATTIRE`, or `ACCESSORIES` — so later category edits could never rewrite a visit's history. When the item is dedicated to a drive pool and its drive is `ACTIVE`, the line is flagged `is_drive_line` and its `drive_id` names the drive whose bonus pool it consumes; otherwise the flag is false and `drive_id` is null.

Four limits guard line addition, evaluated after the availability checks in this order. First the per-visit allowance: the number of `ACTIVE` general (non-drive) lines on the visit must stay below `general_allowance`, and the number of `ACTIVE` drive lines drawn from any single drive must stay below that drive's per-client pool; a line that would exhaust either budget is rejected with `ERR_ITEM_LIMIT_EXCEEDED`. Second the category caps: a general line is rejected with `ERR_CATEGORY_LIMIT_EXCEEDED` when adding it would push the visit's `ACTIVE` general lines sharing its `category_snapshot` past the category's cap — `COATS` allows 2 per visit, `INTERVIEW_ATTIRE` allows 1, and all other categories are uncapped; drive lines are exempt from category caps because the drive pool already bounds them. Third the rolling item cap: when the client's `items_in_30d` plus the `ACTIVE` lines already on this visit plus the new line would exceed 30, the addition is rejected with `ERR_ROLLING_ITEM_CAP_EXCEEDED`. Fourth, for an item dedicated to a drive, the drive must be `ACTIVE` at line-add time, or the addition fails with `ERR_DRIVE_NOT_ACTIVE`. Note that reserving an item leaves its zone's `current_stock` untouched — the garment is still on the shelf until checkout.

Removing a line releases the reservation: the line must be `ACTIVE` and its visit still `CHECKED_IN`, and the operation moves the line to `RELEASED` while the item returns from `RESERVED` to `STOCKED` with `reserved_visit_id` cleared.

A distributed item can be brought back. Returning a line requires the line to be `DISTRIBUTED` (otherwise `ERR_INVALID_STATE`); the line becomes `RETURNED`, and the item moves from `DISTRIBUTED` back to `STOCKED` in the zone recorded as its `distributed_from_zone_id`, deliberately bypassing the capacity check so a return can never be stranded by a since-filled shelf. The item's `stocked_at` is refreshed, the zone's `current_stock` is incremented and its `posture` recomputed, and the client's `items_in_30d` is recomputed — a returned line no longer counts against the rolling 30-day item tally. Lines can be listed with `visit_id`, `item_id`, `drive_id`, or `status` filters for reverse lookups.

### 3.4. Referral Partners and the Voucher Program

Referral partners are the program's bridge to clients who need extra help. A `ProgramAdmin` registers a partner with a `name` and a `base_voucher_quota` — the partner's base monthly voucher allotment, which may be zero or more. The partner begins `ACTIVE`, and its `activated_month_key` records the UTC month of creation in `YYYY-MM` form; that month anchors the quota arithmetic below.

A partner's effective quota for any month combines the base allotment with unused quota carried forward, month by month. Months are UTC calendar months keyed `YYYY-MM`. For the anchor month, the carryover is 0. For every month after the anchor, the carryover is the smaller of 5 and whatever remains of the previous month's effective quota after that month's issuances — floored at zero so a deficit never propagates. The effective quota for a month is the base allotment plus that month's carryover. Issuance counting is permanent: `vouchers_issued_current_month` counts every voucher created in the clock's current UTC month regardless of later status, and the partner's `current_month_quota` is the effective quota computed for that month. The evaluation order is pinned — months are walked in ascending order from the anchor month to the current month, fully computing each prior month's quota and issuance before deriving the next month's carryover. Issuance is permitted only while `vouchers_issued_current_month` is still below `current_month_quota`; an exhausted quota rejects the issuance with `ERR_VOUCHER_QUOTA_EXHAUSTED`.

Issuing a voucher names the intended recipient by `client_id`, grants `bonus_items` of extra shopping allowance on the redeeming visit (an integer from 1 to 10), optionally sets `waives_frequency` (default false), and fixes an `expires_at` that must lie after the logical clock at issuance. The server mints a unique `code`, records the issuing partner in `partner_id`, stamps `issued_month_key` with the clock's current month, and opens the voucher in `ISSUED` status. Issuance enforces its checks in order: the named client must be `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`), the partner — the resource under which the voucher is created — must be `ACTIVE` (`ERR_PARTNER_SUSPENDED`), and the monthly quota must have room (`ERR_VOUCHER_QUOTA_EXHAUSTED`). Either a `ProgramAdmin` or the partner itself may issue, but a partner acts only under its own partner id.

Redemption happens at check-in, as §3.2 describes; a redeemed voucher stamps `redeemed_at` and its quota consumption is never refunded. A voucher still `ISSUED` may be revoked by the owning partner or a `ProgramAdmin`, moving it to `REVOKED` — attempting to revoke a voucher in any other state is `ERR_INVALID_STATE`, and revocation, like expiry, does not return quota. Expiry itself is lazy per §2.4: at or after `expires_at` the voucher flips to `EXPIRED` on reads, on list operations, and on any redemption attempt. Vouchers can be listed with `partner_id`, `client_id`, `status`, or `code` filters, and the visits that redeemed a given voucher — at most one — can be listed from the voucher.

Suspending a partner, a `ProgramAdmin`-only action, moves it from `ACTIVE` to `SUSPENDED` (any other current state is `ERR_INVALID_STATE`). Suspension blocks all new voucher issuance under that partner, and every previously issued voucher still in `ISSUED` status thereafter fails redemption with `ERR_PARTNER_SUSPENDED`.

### 3.5. Donation Intake, Sorting, and Grading

Donations enter the program as batches. Intake records the `donor_name`, an optional `donor_email`, and the `item_count_declared` — the donor's declared item count, at least 1. A new batch opens in `RECEIVED` status.

Sorting cannot begin until the sorting table is actually staffed. Starting the sort moves a batch from `RECEIVED` to `IN_SORT` and records the operator in `sorted_by_user_id`; it requires at least one signup in `CHECKED_IN` status whose shift has `role_type` `SORTING`, whose shift status is `OPEN` or `LOCKED`, and whose shift window covers the current instant — otherwise the attempt is rejected with `ERR_NO_SORTING_STAFF`. A batch not in `RECEIVED` cannot be started (`ERR_INVALID_STATE`).

While a batch is `IN_SORT`, sorters create and grade items against it — the batch must be `IN_SORT` or item creation fails with `ERR_INVALID_STATE`. Each item record names its `donation_batch_id`, its `category` (`ADULT_TOPS`, `ADULT_BOTTOMS`, `CHILDRENS`, `COATS`, `INTERVIEW_ATTIRE`, or `ACCESSORIES`), its `season` (`WINTER`, `SUMMER`, or `ALL_SEASON`), and its `quality_grade` (`NEW_WITH_TAGS`, `GOOD`, `FAIR`, or `REJECT`), and may optionally dedicate the item to a drive pool via `drive_id`. The grader is recorded in `graded_by_user_id`. An item graded `REJECT` goes straight to `REJECTED` status and awaits the recycling channel; every other grade lands in `PENDING_STOCK`. The batch tracks how many items have been created in `items_created_count`, and the moment that count reaches `item_count_declared` the batch advances automatically from `IN_SORT` to `SORTED`.

Closing finishes the batch. A `VolunteerLead` or `ProgramAdmin` moves a `SORTED` batch to `CLOSED`, recording themselves in `closed_by_user_id`. Segregation of duties applies: the operator who started the sort may not close the same batch — if the acting user's identifier equals the batch's `sorted_by_user_id`, the close is rejected with `ERR_SOD_SORTER_CANNOT_CLOSE`.

### 3.6. Stocking, Quarantine, and Storage Zones

Storage zones are the physical model of the stockroom. A `ProgramAdmin` creates a zone with a globally unique `zone_code` (a duplicate is rejected with `ERR_ZONE_CODE_TAKEN`), a `season_policy` of `WINTER`, `SUMMER`, or `ALL_SEASON`, and a `capacity_items` of at least 1. A new zone starts with `current_stock` 0 and posture `AVAILABLE`. Zones can be listed and filtered by `posture`.

A `ProgramAdmin` may update a zone's `capacity_items` or `season_policy`; the update carries the optimistic-concurrency field of §2.7, increments the zone's `version`, and recomputes `posture`. The new capacity may not be set below the zone's live `current_stock` — such an update is rejected with `ERR_CAPACITY_BELOW_STOCK`.

Stocking shelves an item. The checks run in order: the item must be `PENDING_STOCK` (`ERR_INVALID_STATE`); the target zone must not be `FULL` — its `current_stock` must still be below `capacity_items`, an inclusive boundary per §2.8 (`ERR_ZONE_FULL`); the item's season must be compatible with the zone's policy (`ERR_SEASON_INCOMPATIBLE`); and when the item is dedicated to a drive pool, that drive must be `UPCOMING` or `ACTIVE` (`ERR_DRIVE_NOT_ACTIVE`). On success the item becomes `STOCKED`, its `storage_zone_id` names the zone, `stocked_at` is stamped from the logical clock, the zone's `current_stock` is incremented, and the zone's `posture` is recomputed. Items can be listed with `donation_batch_id`, `storage_zone_id`, `drive_id`, `recycling_batch_id`, `status`, `season`, or `category` filters.

Quarantine pulls a stocked item off the shelf. A `VolunteerLead` or `ProgramAdmin` moves a `STOCKED` item to `QUARANTINED`; the item leaves the shelf, so the zone's `current_stock` is decremented and `posture` recomputed. Releasing quarantine takes an `outcome`: with `RESTOCK` the item returns to `STOCKED` in the same zone it was pulled from, bypassing the capacity check — a quarantined garment must never be stranded by a shelf that filled behind it — with `stocked_at` refreshed and the zone's stock and posture cascaded; with `REJECT` the item becomes `REJECTED`, its `storage_zone_id` is cleared, and it awaits the recycling sweep. Either release requires the item to be `QUARANTINED` (otherwise `ERR_INVALID_STATE`), and quarantine itself requires the item to be `STOCKED`.

### 3.7. Volunteer Shifts and Signups

Volunteers are registered with a `full_name` and an optional `is_lead` flag, defaulting to false; when `is_lead` is true the volunteer authenticates with the `VolunteerLead` role. A volunteer's status is always `ACTIVE` — volunteers are never deactivated in this version of the system.

A shift is created with a `start_at`, an `end_at` that must be strictly later than the start, a `role_type` of `SORTING`, `INTAKE`, or `FLOOR`, and a `capacity_volunteers` of at least 1. New shifts open in `OPEN` status. The shift's `active_signup_count` counts its signups in `SIGNED_UP` or `CHECKED_IN` status.

Signing a volunteer onto a shift takes the `volunteer_id` and creates a signup in `SIGNED_UP` status, with `shift_id` naming the shift. Signup enforces its rules in order: a shift that is `LOCKED` (at capacity) rejects with `ERR_SHIFT_FULL`, and a shift that is `COMPLETED` or `CANCELLED` rejects with `ERR_INVALID_STATE`; the volunteer must not already hold an active signup — one in `SIGNED_UP` or `CHECKED_IN` — on a shift whose window overlaps this one, where overlap is judged on half-open intervals so back-to-back shifts, one ending exactly when the other begins, do not conflict (`ERR_SHIFT_OVERLAP`); and the volunteer must not already be actively signed up on this same shift (`ERR_ALREADY_SIGNED_UP`). Each new signup increments `active_signup_count`, and the moment the count reaches `capacity_volunteers` the shift locks automatically from `OPEN` to `LOCKED`.

Cancellation and check-in are ownership-scoped: a `Volunteer` may cancel or check in only their own signup — the signup's `volunteer_id` must equal the acting user's identifier — while `VolunteerLead` and `ProgramAdmin` act on any signup; acting on another volunteer's signup is `ERR_FORBIDDEN`. Cancelling a `SIGNED_UP` signup moves it to `CANCELLED`, decrements the shift's `active_signup_count`, and when a `LOCKED` shift drops back below capacity it reopens automatically from `LOCKED` to `OPEN`. Checking in requires the signup to be `SIGNED_UP` (otherwise `ERR_INVALID_STATE`), the shift to be `OPEN` or `LOCKED`, and the current instant to fall on or after the shift's `start_at` and on or before its `end_at` — outside that window the check-in is `ERR_SHIFT_NOT_IN_WINDOW`. A successful check-in moves the signup to `CHECKED_IN` and stamps `checked_in_at`.

Two staff actions close a shift out. Completing a shift — allowed once the clock has reached the shift's `end_at`, otherwise `ERR_SHIFT_NOT_IN_WINDOW` — moves an `OPEN` or `LOCKED` shift to `COMPLETED` and settles its signups: those still `SIGNED_UP` become `NO_SHOW`, and those `CHECKED_IN` become `COMPLETED`. Cancelling an `OPEN` or `LOCKED` shift moves it to `CANCELLED` and cascades every `SIGNED_UP` and `CHECKED_IN` signup to `CANCELLED`. A volunteer's signups and a shift's signups can each be listed, filtered by `status`.

### 3.8. Special Drives and Seasonal Rotation

Special drives concentrate donations toward a program goal. A `ProgramAdmin` creates a drive with a `drive_type` of `INTERVIEW_ATTIRE` or `WINTER_COATS`; the `target_category` — the item category the drive boosts — must be `INTERVIEW_ATTIRE` for an interview-attire drive and `COATS` for a winter-coats drive, and any other pairing is rejected as `ERR_INVALID_REQUEST`. The drive window runs from `start_at` to `end_at`, both bounds inclusive, with the end strictly after the start, and `bonus_items_per_client` — the per-client allowance drawn from the drive pool — must be at least 1. Drives of the same `drive_type` may not crowd one another: a new drive whose window conflicts with another same-type drive's window inside a 7-day buffer is rejected with `ERR_DRIVE_WINDOW_CONFLICT`. A new drive opens `UPCOMING`.

Drive status advances lazily per §2.4: a drive whose window has arrived becomes `ACTIVE`, and a drive whose window has passed becomes `CLOSED`. A `ProgramAdmin` may also close a drive early from `UPCOMING` or `ACTIVE`; closing an already `CLOSED` drive is `ERR_INVALID_STATE`. When a drive closes, items dedicated to its pool that are already `STOCKED` remain stocked, but they can no longer be distributed — line addition requires an `ACTIVE` drive per §3.3.

At check-in, every `ACTIVE` drive grants the visit up to `bonus_items_per_client` additional lines, provided each such line's item is dedicated to that drive's pool. Drive lines never consume `general_allowance`, and general items never consume drive pools; the two budgets are accounted separately.

Seasonal rotation moves the stockroom between its seasonal postures. A `ProgramAdmin` schedules a rotation with a `target_season` of `WINTER` or `SUMMER` and an execution window from `window_start` to `window_end`, both bounds inclusive and the end strictly after the start; the rotation opens `SCHEDULED`. Executing the rotation requires it to be `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and the current instant to lie inside the window, boundaries inclusive (otherwise `ERR_ROTATION_OUTSIDE_WINDOW`).

Execution runs two phases in a fixed order. Phase-out comes first: every `STOCKED` item whose `season` is neither the `target_season` nor `ALL_SEASON` moves to `OFF_SEASON`, leaving its zone — `storage_zone_id` is cleared, the zone's `current_stock` is decremented, and its `posture` recomputed, item by item. Phase-in follows: every `OFF_SEASON` item whose `season` equals the `target_season` is considered for restocking in creation order, oldest first, with no identifier tie-break ever applied. For each item, the eligible zones are those whose `season_policy` is the `target_season` or `ALL_SEASON` and whose posture is not `FULL`; they are ranked by `current_stock` ascending, ties broken by the zone's own creation timestamp ascending, and the item is placed into the first zone in that ranking — `storage_zone_id` set, `stocked_at` stamped, stock incremented, posture recomputed — before the next item is considered. When no eligible zone remains, the item simply stays `OFF_SEASON`; an empty placement pool is not an error. The rotation stamps `executed_at` and records the phase totals in `moved_out_count` and `moved_in_count`. A scheduled rotation may instead be cancelled, moving it from `SCHEDULED` to `CANCELLED` (any other state is `ERR_INVALID_STATE`).

### 3.9. Textile Recycling and Impact Reporting

Items too worn to give away leave the program through the recycling channel. A `ProgramAdmin` opens a recycling batch with a `recycler_name` and a `capacity_kg` — the maximum estimated weight the batch accepts, which must be greater than zero. The batch opens `ACCUMULATING`, with `item_count` and `est_weight_kg` derived from its contents.

The sweep assigns waiting items to the batch. Candidates are items in `REJECTED` status whose `recycling_batch_id` is still null, processed in creation order, oldest first, with no identifier tie-break ever applied. Starting from the batch's current `est_weight_kg`, the sweep considers each candidate in turn: if adding the item's estimated weight would push the running total beyond the batch's `capacity_kg`, the sweep stops immediately — it does not skip ahead to a lighter item; otherwise the item's `recycling_batch_id` is set to the batch and its estimated weight joins the running total. When the sweep finishes, the batch's `est_weight_kg` reflects the running total and `item_count` is the number of assigned items.

Estimated weights are fixed per category: an `ADULT_TOPS` item is estimated at 0.40 kg, `ADULT_BOTTOMS` at 0.60 kg, `CHILDRENS` at 0.30 kg, `COATS` at 1.50 kg, `INTERVIEW_ATTIRE` at 0.80 kg, and `ACCESSORIES` at 0.20 kg.

Sealing the batch — which requires the batch to be `ACCUMULATING` (otherwise `ERR_INVALID_STATE`) and then to hold at least one assigned item (otherwise `ERR_RECYCLING_EMPTY`) — computes the provisional settlement. The recycler's per-kilogram rates are 45 cents for `ADULT_TOPS`, 45 for `ADULT_BOTTOMS`, 38 for `CHILDRENS`, 52 for `COATS`, 60 for `INTERVIEW_ATTIRE`, and 30 for `ACCESSORIES`. For each assigned item, its estimated weight is multiplied by its category's rate and the result rounded half up to a whole cent; `provisional_credit_cents` is the sum of those per-item amounts, and `est_weight_kg` is the sum of the estimated weights at two decimal places. Sealing also moves every assigned item from `REJECTED` to `RECYCLED` and records the operator in `sealed_by_user_id`.

Recording pickup settles the batch for real. The request must first carry an `actual_weight_kg` greater than zero (otherwise `ERR_INVALID_REQUEST`), the batch must then be `SEALED` (otherwise `ERR_INVALID_STATE`), and finally segregation of duties applies: the operator recording pickup must not be the one who sealed the batch — a matching identifier against `sealed_by_user_id` is rejected with `ERR_SOD_SEALER_CANNOT_PICKUP`. The final settlement blends composition away and prices the scale weight at a single tiered rate: below 100 kilograms the rate is 40 cents per kilogram; from 100 kilograms up to but not including 500 kilograms the rate is 44; at 500 kilograms and above the rate is 50 — boundaries are inclusive upward. `final_credit_cents` is the actual weight multiplied by the applicable tier rate, rounded half up to a whole cent. The operator is recorded in `picked_up_by_user_id`, and the batch moves to `PICKED_UP`.

The program's impact report, available to `ProgramAdmin` and `VolunteerLead`, takes a `zone_id` and measures inventory turnover over the trailing 28 days — a half-open window in which an event exactly 28 days before the present is excluded. For the addressed zone, `window_distributed` counts items whose `distributed_from_zone_id` names the zone and whose `distributed_at` falls inside the window; `window_stocked` counts items whose `stocked_at` falls inside the window and which either still name the zone in `storage_zone_id` or left it via distribution — an item stocked into the zone and distributed within the window counts on both sides. From those, `stock_at_window_start` is the zone's live `current_stock` plus `window_distributed` minus `window_stocked`. Two turnover ratios are reported: `turnover_current_basis` divides `window_distributed` by the live `current_stock`, substituting a denominator of 1 when the shelf stands empty; `turnover_average_basis` divides `window_distributed` by the mean of `stock_at_window_start` and `current_stock` rounded half up to a whole number, again substituting 1 when that mean is zero. The current-basis figure penalizes a zone that just received a restock wave; the average-basis figure smooths it. Both ratios are reported at four decimal places, rounded half up, alongside the raw `zone_id`, `current_stock`, `window_distributed`, `window_stocked`, and `stock_at_window_start` figures. The same response carries network-wide totals: `items_distributed_total`, `unique_clients_served`, `recycled_items_total`, `recycling_provisional_credit_cents_total`, and `recycling_final_credit_cents_total`.

## 4. Endpoint Definitions

Operations that create a new resource — registering a client, opening a visit, adding a distribution line, intaking a batch, grading an item, creating a zone, scheduling a rotation, registering a volunteer, creating a shift, signing up, creating a partner, issuing a voucher, creating a drive, or opening a recycling batch — return `201 Created`. Operations that act on an existing resource, including state transitions, updates, sweeps, and the clock advance, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/closet/_clock/set_current_utc` | Advance the logical clock | ProgramAdmin |
| POST | `/closet/clients` | Register a client | ProgramAdmin, VolunteerLead, Volunteer |
| GET | `/closet/clients` | List clients | ProgramAdmin, VolunteerLead, Volunteer |
| GET | `/closet/clients/{id}` | Read a client (self or staff) | ProgramAdmin, VolunteerLead, Volunteer, Client |
| PATCH | `/closet/clients/{id}` | Update household size / eligibility tier (OCC) | ProgramAdmin, VolunteerLead |
| POST | `/closet/clients/{id}/suspend` | Suspend a client | ProgramAdmin, VolunteerLead |
| POST | `/closet/clients/{id}/reinstate` | Reinstate a client | ProgramAdmin, VolunteerLead |
| POST | `/closet/clients/{id}/visits` | Check in a visit; optional voucher redemption | ProgramAdmin, VolunteerLead, Volunteer |
| GET | `/closet/clients/{id}/visits` | List a client's visits | ProgramAdmin, VolunteerLead, Volunteer, Client |
| GET | `/closet/visits/{id}` | Read a visit | ProgramAdmin, VolunteerLead, Volunteer, Client |
| POST | `/closet/visits/{id}/lines` | Add an item to a visit (item becomes reserved) | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/visits/{id}/checkout` | Finalize a visit; lines become distributed | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/visits/{id}/void` | Void an open visit; release reservations | ProgramAdmin, VolunteerLead |
| GET | `/closet/vouchers/{id}/visits` | List visits that redeemed this voucher (0–1) | ProgramAdmin, VolunteerLead, Volunteer |
| GET | `/closet/distribution-lines/{id}` | Read a distribution line | ProgramAdmin, VolunteerLead, Volunteer |
| GET | `/closet/distribution-lines` | List distribution lines (reverse lookups) | ProgramAdmin, VolunteerLead, Volunteer |
| DELETE | `/closet/distribution-lines/{id}` | Remove an active line; item returns to stocked | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/distribution-lines/{id}/return` | Return a distributed item to its zone | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/donation-batches` | Intake a donation batch | ProgramAdmin, VolunteerLead, Volunteer |
| GET | `/closet/donation-batches/{id}` | Read a batch | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/donation-batches/{id}/start-sorting` | Begin sorting (requires checked-in sorting staff) | VolunteerLead, Volunteer |
| POST | `/closet/donation-batches/{id}/items` | Create and grade an item during sorting | VolunteerLead, Volunteer |
| POST | `/closet/donation-batches/{id}/close` | Close a sorted batch (closer differs from sorter) | ProgramAdmin, VolunteerLead |
| GET | `/closet/items/{id}` | Read an item | ProgramAdmin, VolunteerLead, Volunteer |
| GET | `/closet/items` | List items (reverse lookups and filters) | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/items/{id}/stock` | Place a pending item into a zone | VolunteerLead, Volunteer |
| POST | `/closet/items/{id}/quarantine` | Pull a stocked item off the shelf | ProgramAdmin, VolunteerLead |
| POST | `/closet/items/{id}/release-quarantine` | Release quarantine to restock or reject | ProgramAdmin, VolunteerLead |
| POST | `/closet/storage-zones` | Create a storage zone | ProgramAdmin |
| GET | `/closet/storage-zones/{id}` | Read a zone | ProgramAdmin, VolunteerLead, Volunteer |
| GET | `/closet/storage-zones` | List zones | ProgramAdmin, VolunteerLead, Volunteer |
| PATCH | `/closet/storage-zones/{id}` | Update capacity / season policy (OCC) | ProgramAdmin |
| POST | `/closet/seasonal-rotations` | Schedule a seasonal rotation | ProgramAdmin |
| GET | `/closet/seasonal-rotations/{id}` | Read a rotation | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/seasonal-rotations/{id}/execute` | Execute phase-out then capacity-gated phase-in | ProgramAdmin |
| POST | `/closet/seasonal-rotations/{id}/cancel` | Cancel a scheduled rotation | ProgramAdmin |
| POST | `/closet/volunteers` | Register a volunteer | ProgramAdmin, VolunteerLead |
| GET | `/closet/volunteers/{id}` | Read a volunteer | ProgramAdmin, VolunteerLead, Volunteer |
| GET | `/closet/volunteers/{id}/signups` | List a volunteer's signups | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/shifts` | Create a volunteer shift | ProgramAdmin, VolunteerLead |
| GET | `/closet/shifts/{id}` | Read a shift | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/shifts/{id}/cancel` | Cancel a shift; cascades signups | ProgramAdmin, VolunteerLead |
| POST | `/closet/shifts/{id}/complete` | Complete a shift at/after its end | ProgramAdmin, VolunteerLead |
| POST | `/closet/shifts/{id}/signups` | Sign a volunteer onto a shift | ProgramAdmin, VolunteerLead, Volunteer |
| GET | `/closet/shifts/{id}/signups` | List a shift's signups | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/shifts/{id}/signups/{sid}/cancel` | Cancel a signed-up signup | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/shifts/{id}/signups/{sid}/check-in` | Check in a signup inside the shift window | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/referral-partners` | Create a referral partner | ProgramAdmin |
| GET | `/closet/referral-partners/{id}` | Read a partner (self or staff) | ProgramAdmin, VolunteerLead, Volunteer, ReferralPartner |
| POST | `/closet/referral-partners/{id}/suspend` | Suspend a partner | ProgramAdmin |
| POST | `/closet/referral-partners/{id}/vouchers` | Issue a voucher to a client | ProgramAdmin, ReferralPartner |
| GET | `/closet/vouchers/{id}` | Read a voucher (lazy expiry evaluation) | ProgramAdmin, VolunteerLead, Volunteer, Client, ReferralPartner |
| GET | `/closet/vouchers` | List vouchers (reverse lookups) | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/vouchers/{id}/revoke` | Revoke an issued voucher | ProgramAdmin, ReferralPartner |
| POST | `/closet/drives` | Create a special drive (buffered window conflict check) | ProgramAdmin |
| GET | `/closet/drives/{id}` | Read a drive (lazy status advancement) | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/drives/{id}/close` | Close a drive early | ProgramAdmin |
| POST | `/closet/recycling-batches` | Open a recycling batch | ProgramAdmin |
| GET | `/closet/recycling-batches/{id}` | Read a recycling batch | ProgramAdmin, VolunteerLead, Volunteer |
| POST | `/closet/recycling-batches/{id}/sweep` | Assign unassigned rejected items until capacity would be exceeded | ProgramAdmin |
| POST | `/closet/recycling-batches/{id}/seal` | Seal the batch; provisional credit; items recycled | ProgramAdmin |
| POST | `/closet/recycling-batches/{id}/pickup` | Record pickup with actual scale weight | ProgramAdmin |
| GET | `/closet/reports/impact` | Impact and turnover report (trailing 28 days) | ProgramAdmin, VolunteerLead |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ITEM_NOT_AVAILABLE` | 409 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_PARTNER_SUSPENDED` | 409 |
| `ERR_VISIT_COOLDOWN_ACTIVE` | 409 |
| `ERR_VISIT_LIMIT_REACHED` | 409 |
| `ERR_VOUCHER_EXPIRED` | 409 |
| `ERR_SHIFT_NOT_IN_WINDOW` | 409 |
| `ERR_ROTATION_OUTSIDE_WINDOW` | 409 |
| `ERR_NO_SORTING_STAFF` | 409 |
| `ERR_ZONE_FULL` | 409 |
| `ERR_SEASON_INCOMPATIBLE` | 409 |
| `ERR_SHIFT_FULL` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_ALREADY_SIGNED_UP` | 409 |
| `ERR_ITEM_LIMIT_EXCEEDED` | 409 |
| `ERR_CATEGORY_LIMIT_EXCEEDED` | 409 |
| `ERR_ROLLING_ITEM_CAP_EXCEEDED` | 409 |
| `ERR_EMPTY_VISIT_CHECKOUT` | 409 |
| `ERR_VOUCHER_QUOTA_EXHAUSTED` | 409 |
| `ERR_ZONE_CODE_TAKEN` | 409 |
| `ERR_DRIVE_WINDOW_CONFLICT` | 409 |
| `ERR_RECYCLING_EMPTY` | 409 |
| `ERR_CAPACITY_BELOW_STOCK` | 409 |
| `ERR_VOUCHER_NOT_REDEEMABLE` | 409 |
| `ERR_VOUCHER_CLIENT_MISMATCH` | 409 |
| `ERR_DRIVE_NOT_ACTIVE` | 409 |
| `ERR_SOD_SORTER_CANNOT_CLOSE` | 409 |
| `ERR_SOD_SEALER_CANNOT_PICKUP` | 409 |
