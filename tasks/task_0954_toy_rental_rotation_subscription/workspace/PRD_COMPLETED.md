# Toy Rental & Rotation Subscription API — Product Requirements Document

## 1. Introduction

Families outgrow toys faster than they outgrow the subscription. This document specifies the Toy Rental & Rotation Subscription API: a platform through which subscribing households receive rotating boxes of physical toys matched to each child's developmental stage, keep them for a fixed rental period, and ship them back for inspection, sanitization, and recirculation. Because the business rents a finite pool of physical copies, the system's central problem is allocation — deciding which waiting member receives a copy the moment one becomes available — while protecting hygiene standards, enforcing age-appropriateness, and recovering the cost of damaged, incomplete, late, or lost toys through a wallet-and-card fee pipeline.

The API covers the full commercial loop: member registration and child profiles, plan and catalog administration, wishlist capture with time-boxed holds, rotation-box planning with slot and swap limits, outbound and return shipping with carrier events, per-item inspection with damage and missing-piece assessment, member buy-out of loved toys, subscription pause and cancellation, fee payment, waiver, and dispute, and an operations checkpoint that sweeps allocations, expires stale holds, and activates or releases pause windows. All endpoints are mounted under the `/toy-rental` prefix. Every time-dependent rule in the system reads a controllable logical clock rather than wall-clock time, so that cadence, holds, pauses, and sanitization buffers behave deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request missing either header, or presenting a role the platform does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The platform recognizes five roles, spelled exactly as follows: `Anonymous`, `Member`, `OperationsManager`, `CustomerService`, and `PlatformAdmin`. Each endpoint admits a fixed list of roles (enumerated in §4); a caller whose role is not on that endpoint's list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Roles differ in how `X-User-ID` binds to persisted data. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting Member record, and ownership checks on any resource that belongs to a member compare the resource's owning-member reference to `X-User-ID` — whether that reference is the member path identifier itself, a subscription's owning member, a rotation box reached through its subscription, a box item reached through its box, a wishlist entry's owning member, or a fee reached through its subscription. A member touching a resource owned by a different member is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `Anonymous`, `OperationsManager`, `CustomerService`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

The roles partition responsibility. `Anonymous` callers are unauthenticated visitors who may only register a new member account. A `Member` is the subscribing parent: they manage child profiles, subscriptions (pause, resume, cancel, plan change), wishlist entries, rotation-box contents, buy-outs and loss reports, returns, and fee payments and disputes on their own resources. An `OperationsManager` is the warehouse operator: shipping, carrier-event recording, inspection, box closure, sanitization completion, and the allocation checkpoint. A `CustomerService` agent handles wallet adjustments, fee waivers, dispute resolution, and member account closure. A `PlatformAdmin` administers plans, the catalog, physical copies, and the logical clock.

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

### 2.3. Pagination

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. Neither parameter is ever rejected: a missing or non-numeric `limit` falls back to 10 and a numeric one below 1 or above 100 is clamped into that range, and `offset` behaves likewise with a fallback of 0 and a floor of 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with timestamp ties broken by creation order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, both stamped from the logical clock of §2.5; `updated_at` refreshes on every mutation, including mutations caused by system cascades rather than direct client writes. The `version` field is a system-managed integer that starts at 1 at creation and increments by one on every mutation of the resource — again including cascade-driven ones — and serves as the basis for optimistic concurrency control. The append-only `CreditLedgerEntry` is the single exception: it carries `id` and `created_at` only, while `updated_at` and `version` are absent, because ledger entries are never modified after being written.

### 2.5. The Logical Clock

All time-dependent behavior — cadence due dates, hold expiry, pause windows, sanitization buffers, age computation, late fees — is evaluated against a server-side logical clock, never against wall-clock time. When the clock-positioning capability has never been invoked since startup, the logical clock reads exactly 2026-05-01T00:00:00Z; the server must not fall back to wall-clock time under any circumstance. A `PlatformAdmin`-only, test-driving capability positions the logical clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc` value.

### 2.6. Nested Path Resolution and Validation Order

Requests that target nested resources validate path identifiers strictly left to right, rejecting with the 404 that corresponds to the first missing resource: `ERR_MEMBER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_COPY_NOT_FOUND`, `ERR_WISHLIST_ENTRY_NOT_FOUND`, `ERR_BOX_NOT_FOUND`, `ERR_BOX_ITEM_NOT_FOUND`, `ERR_FEE_NOT_FOUND`, or `ERR_SHIPMENT_NOT_FOUND` (each HTTP 404). A request for a box item under a non-existent box therefore fails with `ERR_BOX_NOT_FOUND` before the item identifier is ever examined. Identifiers carried in the request body that reference a target resource — a `plan_id`, `catalog_item_id`, `toy_copy_id`, `new_toy_copy_id`, or `rotation_box_id` — resolve on this same tier, immediately after path existence and before ownership, surfacing the corresponding `ERR_PLAN_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_COPY_NOT_FOUND`, or `ERR_BOX_NOT_FOUND`.

Beyond existence, every request passes through a fixed validation pipeline, and the order matters because it determines which error surfaces when several rules are violated at once. The pipeline evaluates, in order: (1) header authentication (`ERR_UNAUTHENTICATED`); (2) role authorization (`ERR_UNAUTHORIZED_ROLE`); (3) left-to-right path existence (the 404 family above); (4) member ownership (`ERR_FORBIDDEN_OWNERSHIP`); (5) state-legality gates and, on the same tier, optimistic-concurrency stale-version checks — the state gates surface domain-specific codes such as `ERR_MEMBER_SUSPENDED`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_COPY_NOT_AVAILABLE`, `ERR_FEE_NOT_INVOICED`, `ERR_MEMBER_HAS_OPEN_BOX`, or `ERR_PREVIOUS_BOX_OPEN` where the workflow defines one, and otherwise `ERR_INVALID_STATE` (HTTP 409), while a stale version surfaces `ERR_STALE_VERSION` (HTTP 412); (6) business-safety gates — the developmental age gate (`ERR_AGE_INCOMPATIBLE`) and sanitization validity (`ERR_NEEDS_RESANITIZATION`); (7) temporal rules — cadence due (`ERR_BOX_CYCLE_NOT_DUE`), pause-window overlap (`ERR_PAUSE_WINDOW_OVERLAP`), hold expiry (`ERR_HOLD_EXPIRED`), and the sanitization buffer (`ERR_SANITIZATION_BUFFER_ACTIVE`); (8) constraint rules — uniqueness violations (`ERR_EMAIL_TAKEN`, `ERR_SUBSCRIPTION_ACTIVE_EXISTS`, `ERR_WISHLIST_DUPLICATE`, and duplicate copy barcodes), slot capacity (`ERR_SLOT_CAPACITY_EXCEEDED`), swap allowance (`ERR_SWAP_ALLOWANCE_EXCEEDED`), pause allowance (`ERR_PAUSE_ALLOWANCE_EXCEEDED`), an open sibling box (`ERR_PREVIOUS_BOX_OPEN`), and empty-box shipping (`ERR_BOX_EMPTY`); (9) referential rules — retired catalog items (`ERR_CATALOG_ITEM_RETIRED`) and, only where the workflow evaluates reservation last (hold acceptance, §3.4), a held copy no longer reserved to the caller (`ERR_COPY_NOT_AVAILABLE`); (10) fiscal rules — wallet sufficiency (`ERR_WALLET_INSUFFICIENT`), dispute-round limits (`ERR_DISPUTE_LIMIT_REACHED`), and outstanding fees (`ERR_FEES_OUTSTANDING`); and finally (11) request-body shape validation (`ERR_VALIDATION`, HTTP 400), which rejects missing required fields, unknown or computed/system-managed fields supplied by the client, out-of-range enum values, a `min_age_months` greater than `max_age_months`, a `birthdate` after the logical clock date, or a duplicate copy `barcode`. Body-shape validation runs last by design, so that a request violating a domain rule surfaces the domain error rather than a generic malformed-body rejection.

### 2.7. Monetary Representation and Rounding

All monetary amounts are represented as integer cents — wallet balances, ledger amounts, plan prices, catalog retail and replacement values, fee amounts, and buy-out figures alike; no floating-point money appears anywhere in the API. Where a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent. Two workflows pin the rounding order precisely. Inspection fees round each fee component per item first and only then sum the already-rounded components; summing raw values and rounding once at the end yields different cents and is incorrect. Buy-out pricing rounds the discounted-and-depreciated gross figure and the rental credit separately, both half up, before subtracting the credit from the gross.

### 2.8. Optimistic Concurrency Control

Three writes are guarded by optimistic concurrency control; each requires a request-body field carrying the version of the parent resource as the caller last observed it.

- Changing a subscription's plan (`PATCH /toy-rental/subscriptions/{id}/plan`) requires `expected_subscription_version`. If it does not equal the subscription's current `version` — because box creation, a pause or resume, or an earlier plan change has advanced the subscription since the caller last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), since the caller's view of the plan terms is stale.
- Creating the next rotation box (`POST /toy-rental/subscriptions/{id}/rotation-boxes`) likewise requires `expected_subscription_version`: a stale version means the cadence anchor, plan terms, or pause state changed since the caller last read the subscription, and the create is refused with `ERR_STALE_VERSION` (HTTP 412) rather than building a box on outdated cycle terms.
- Adding an item to a rotation box (`POST /toy-rental/rotation-boxes/{id}/items`) requires `expected_rotation_box_version`; a mismatch with the box's current `version` — advanced by a prior add or swap — is rejected with `ERR_STALE_VERSION` (HTTP 412) instead of silently appending to a changed box.

Endpoints not listed here do not accept a version field.

### 2.9. The Wallet Ledger and Member Suspension

Each member's store-credit balance lives in an append-only ledger of `CreditLedgerEntry` rows. The invariant is absolute: a member's `wallet_credit_cents` always equals the sum of `amount_cents` across all of that member's ledger entries. The field is recomputed after every ledger append and is never written directly. Ledger `reason` values are `PROMO_CREDIT`, `SUPPORT_ADJUSTMENT`, `FEE_CHARGE`, `FEE_SETTLED_CARD`, `FEE_SETTLED_WALLET`, `WALLET_DEBIT`, `FEE_WAIVER`, and `BUYOUT_CREDIT_APPLIED`; positive amounts credit the member and negative amounts debit, and an entry's amount is never zero. Every entry also carries a `note` string — the caller-supplied note where the originating workflow accepts one, otherwise empty.

The same recompute drives account suspension. Whenever a ledger append leaves `wallet_credit_cents` below −5,000 cents — a debt exceeding fifty dollars — the member's `status` flips from `ACTIVE` to `SUSPENDED`; a later append that brings the balance back to −5,000 cents or higher restores `ACTIVE`. The boundary is exact: a balance of precisely −5,000 cents keeps the member `ACTIVE`. While `SUSPENDED`, every member-gated mutation fails with `ERR_MEMBER_SUSPENDED` (HTTP 409): creating a rotation box, adding or swapping a box item, buying out or reporting lost a toy, creating a wishlist entry, accepting a hold, and pausing or resuming a subscription. A member's third state, `CLOSED`, is terminal and is reached only through support-driven account closure (§3.9).

### 2.10. Sanitization Hygiene Protocol

A physical copy may enter a member's home only when its sanitization is valid. Validity has exactly two forms: the copy is factory-sealed — `condition_grade` `NEW` with `last_sanitized_at` still null — or its `last_sanitized_at` lies within 30 days of the logical clock (a sanitization exactly 30 days old is still valid). A copy failing both forms is sanitization-stale, and attempts to slot it into a box, swap to it, or accept it from a hold are rejected with `ERR_NEEDS_RESANITIZATION` (HTTP 422); the allocation sweep likewise considers only sanitization-valid copies.

Returned copies pass through a mandatory wash cycle. Completing sanitization requires the copy to be in `SANITIZING` and at least 24 hours to have elapsed since `sanitization_started_at`; an earlier completion attempt is rejected with `ERR_SANITIZATION_BUFFER_ACTIVE` (HTTP 422). This buffer guarantees a minimum 24-hour gap between consecutive loan intervals of the same physical copy.

### 2.11. Cascades and Hierarchical Consistency

The resource graph is a hybrid tree: a Member owns child profiles, subscriptions, wishlist entries, and ledger entries; a subscription owns rotation boxes and fee assessments; a rotation box owns box items and shipments; a catalog item owns its physical copies. Box items cross-reference physical copies, fees cross-reference their source items and boxes, and a swap-created box item references the item it replaced. The consistency model is immediate: when one operation mutates several resources — a pause cancelling a planned box, a swap releasing a copy that promotes a waiting wishlist entry, an inspection emitting fees that debit the wallet and suspend the member — every effect is applied atomically and is visible in that same request's response. Every resource touched by a cascade counts as mutated: its `updated_at` refreshes and, where the resource carries one, its `version` increments by one.

Whenever a reserved physical copy is released back to `AVAILABLE` — through a swap, a hold expiring or being cancelled, or the cancellation of a planned box — the release immediately triggers a targeted allocation sweep for that copy's catalog item (§3.4). A released copy is never left idle when eligible demand exists.

## 3. Business Logic & Workflows

### 3.1. Membership, Child Profiles, and the Developmental Age Gate

Registration is open to `Anonymous` callers and asks for an `email`, a `full_name`, and a `password`. Email addresses are unique across all members, compared exactly and case-sensitively: a duplicate registration is rejected with `ERR_EMAIL_TAKEN` (HTTP 409). The `password` is write-only and is never echoed in any response. A freshly registered member starts with `status` `ACTIVE` and a `wallet_credit_cents` of zero. Members — and support or platform staff — can later read the member record, which exposes the live wallet balance alongside the account status.

A subscribing household describes its children through child profiles, each created by the owning `Member` with a `name` and a `birthdate` in ISO 8601 `YYYY-MM-DD` form; a birthdate after the current logical clock date is rejected with `ERR_VALIDATION`. Every profile is stamped with the owning `member_id` at creation, and members and support agents can list a member's children. From the birthdate the server derives two computed fields. The `age_months` field counts whole calendar months between the birthdate and the logical clock date, where a month completes on the same day-of-month as the birthdate — clamped to the month end when the target month is shorter — so a child born on 2025-05-02 reads 11 months when the clock stands at 2026-05-01. The `developmental_stage` field bands that age as `INFANT` for 0–11 months, `TODDLER` for 12–35, `PRESCHOOLER` for 36–59, and `EARLY_SCHOOL` for 60 months and beyond.

The calendar-month variant is canonical: it alone feeds `age_months`, `developmental_stage`, and every hard eligibility gate. A catalog item fits a household when at least one of the member's child profiles satisfies the item's inclusive age range — the child's calendar `age_months` is at least the item's `min_age_months` and at most its `max_age_months`. Slotting an item into a box, swapping to a different copy, and accepting a hold all re-evaluate this gate and fail with `ERR_AGE_INCOMPATIBLE` (HTTP 422) when no child qualifies. Catalog browsing is deliberately more permissive: the optional `child_id` filter on the catalog list applies a rolling variant — elapsed calendar days divided by 30, rounded down and floored at zero — purely as a suggestion aid, and a `child_id` naming a non-existent child profile is rejected with `ERR_VALIDATION`. Under that variant the same child born 2025-05-02 reads 12 months at clock 2026-05-01, so the browse list can suggest an item that the hard gate still rejects. Members may also filter the catalog by `developmental_stage` or `status`, and both filters compose with pagination.

### 3.2. Plans, Catalog, and the Physical Copy Pool

A `PlatformAdmin` shapes the commercial offering through subscription plans. A plan carries a display `name`, a `monthly_fee_cents` price of at least 0 (billing itself is out of scope), `toys_per_box` — the maximum number of slotted items a rotation box may hold, at least 1 — `swap_allowance_per_cycle`, the number of pre-shipment swaps a box permits (zero or more), `max_holds`, the maximum number of held wishlist entries a member may carry at one time for sweep eligibility (zero or more), `rotation_cadence_days`, the gap between one box closing and the next cycle becoming due (at least 1 day), `rental_period_days`, the loan length from delivery to due date (at least 1 day), and `buyout_discount_pct`, a fractional discount off retail applied at buy-out that must be at least 0 and strictly less than 1. Plans can be listed and read by members and staff, and support or platform staff can list the subscriptions running on a plan.

The catalog describes each rentable toy. Creating a catalog item takes a `title`, an optional free-text `description` defaulting to empty, the inclusive age bounds `min_age_months` and `max_age_months`, each at least 0 (a minimum above the maximum is rejected with `ERR_VALIDATION`), a `developmental_stages` array naming any of `INFANT`, `TODDLER`, `PRESCHOOLER`, and `EARLY_SCHOOL` as a browse facet, the `piece_count` of the complete toy (at least 1, and the basis for missing-piece fees), a `retail_value_cents` price above zero that anchors buy-out pricing, and a `replacement_value_cents` cost above zero that anchors loss, damage, missing-piece, and late-fee-cap calculations. New items are `ACTIVE`. Retiring an item — a `PlatformAdmin` action allowed only while the item is `ACTIVE`, otherwise `ERR_INVALID_STATE` — moves it to `RETIRED`; existing wishlist entries and physical copies are unaffected, but any new wishlist entry naming the retired item is rejected with `ERR_CATALOG_ITEM_RETIRED` (HTTP 422).

Each catalog item is backed by a pool of physical copies. Minting a copy under a catalog item stamps it with the owning `catalog_item_id` and takes a `barcode` — unique across all copies, with duplicates rejected by `ERR_VALIDATION` — plus an optional `condition_grade` of `NEW`, `GOOD`, `FAIR`, or `WORN`, defaulting to `NEW`. A new copy starts `AVAILABLE`, with `reserved_member_id` null, `sanitization_started_at` null, `last_sanitized_at` null (factory-sealed), and a `sanitization_cycle_count` of zero. Operators can list the copies of a catalog item with an optional `status` filter, review a copy's wishlist demand and the box slots it has occupied, and members can list the copies currently reserved to them.

### 3.3. Subscription Lifecycle: Cadence, Pause Windows, Plan Changes, and Cancellation

A `Member` starts a subscription by naming a `plan_id`. Each member may carry at most one non-`CANCELLED` subscription; a second attempt is rejected with `ERR_SUBSCRIPTION_ACTIVE_EXISTS` (HTTP 409). The subscription starts `ACTIVE` with an initially empty `pause_windows` list, and its cadence anchor `next_cycle_due_at` is initialized to the subscription's `created_at`, so the first box is immediately due. Plan changes keep the same subscription: the member supplies the new `plan_id` together with the optimistic-concurrency field described in §2.8, the update increments the subscription's `version` by one, and the new plan's terms apply to future boxes only — a box already planned keeps the terms it was created under.

Pausing records a half-open date window — start date inclusive, end date exclusive — described by a `start_date` and a `duration_days` length of at least 1, and appended to the subscription's `pause_windows` list as an entry holding `start_date`, `end_date` (the start plus the duration), a `consumed_days` counter that stays null while the window is open, and a `closed` flag that starts false. Two guardrails apply equally to every pause request. First, the allowance: the requested duration plus `paused_days_used_365d` — the sum of consumed pause days across windows whose start date falls within the trailing 365 days of the logical clock, where the currently open window contributes the days elapsed so far and scheduled not-yet-active windows contribute their full duration — must not exceed 60 days; exactly 60 is legal and 61 is rejected with `ERR_PAUSE_ALLOWANCE_EXCEEDED` (HTTP 422). Second, overlap: the new window must not overlap any existing window, with pure adjacency — a start date equal to a prior window's end date — explicitly allowed; violations are rejected with `ERR_PAUSE_WINDOW_OVERLAP` (HTTP 409).

The request's effect depends on timing. When `start_date` is on or before the logical clock date, the pause is immediate: the subscription moves `ACTIVE` → `PAUSED`, `current_pause_end` is set to the window's end date, `paused_days_used_365d` is recomputed, and every `PLANNED` rotation box of the subscription is cancelled — its still-pending items cancel with it, each released copy returns from `RESERVED` to `AVAILABLE`, and each release fires the targeted allocation sweep. When `start_date` lies in the future, the request is a scheduled pause: the window is appended, the subscription remains `ACTIVE` (a self-transition that still increments the subscription's `version` by one), and an operations checkpoint later activates the window once its start date has arrived, applying the same planned-box cancellation cascade at activation. Both forms require the subscription to be `ACTIVE` — otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE` (HTTP 409) — and the member to be unsuspended.

Resuming closes the open window. A member may resume early, and the operations checkpoint auto-resumes a pause once the logical clock reaches `current_pause_end`. Either way the window is stamped `closed` with `consumed_days` set to the whole days between its start date and the earlier of the resume date and the window's end date; `current_pause_end` clears to null; `paused_days_used_365d` is recomputed; the cadence clock, frozen during the pause, is shifted forward — `next_cycle_due_at` moves later by exactly the closed window's `consumed_days` days; and the subscription's `version` increments by one. A member-initiated resume from anything but `PAUSED` fails with `ERR_SUBSCRIPTION_NOT_ACTIVE`, and a suspended member cannot resume at all.

Cancelling is terminal and is permitted from either `ACTIVE` or `PAUSED` — any other state yields `ERR_INVALID_STATE`. An optional `reason` is captured into `cancel_reason`. The cascade is wide: every wishlist entry of the member still `WAITING` or `HELD` is cancelled (held copies are released with the targeted sweep), every `PLANNED` box is cancelled with the same copy-release cascade, and every still-open pause window — the active one and any merely scheduled ones — is discarded from `pause_windows`. Boxes already past `PLANNED` are left alone — they continue their lifecycle to `CLOSED` — and outstanding fees remain payable. The subscription's `version` increments by one.

### 3.4. Wishlist Demand and Hold Allocation

Members express demand by adding catalog items to their wishlist, supplying a `catalog_item_id` and a `rank` — a member-chosen priority where lower numbers come earlier. One open entry per toy per member: a second `WAITING` or `HELD` entry for the same catalog item is rejected with `ERR_WISHLIST_DUPLICATE` (HTTP 409), retired items are refused with `ERR_CATALOG_ITEM_RETIRED`, and suspended members are refused with `ERR_MEMBER_SUSPENDED`. New entries start `WAITING`. Members can list their own entries with an optional `status` filter, and operators can review per-item demand across members.

Allocation sweeps convert waiting demand into time-boxed holds. A sweep runs in targeted form whenever a copy returns to `AVAILABLE`, and globally during the operations checkpoint. For each `AVAILABLE`, sanitization-valid copy — scanned in `created_at` ascending order — the candidate set is the `WAITING` entries for that copy's catalog item whose member holds an `ACTIVE` subscription, whose count of `HELD` entries is below the plan's `max_holds`, and for whom at least one child profile passes the calendar age gate. The winner is the candidate with the lowest `rank`, ties broken by earliest `created_at`. Promotion moves the entry `WAITING` → `HELD`, stamps `held_copy_id` with the chosen copy, sets `hold_expires_at` to exactly 72 hours after the promotion instant, and moves the copy `AVAILABLE` → `RESERVED` with `reserved_member_id` naming the lucky member. When no candidate qualifies, the copy simply stays `AVAILABLE`.

Accepting a hold converts it into a box slot. The member names a target `rotation_box_id`, and the checks are strict: the entry must be `HELD` (otherwise `ERR_INVALID_STATE`); the logical clock must be strictly before `hold_expires_at` — acceptance at or after the expiry instant fails with `ERR_HOLD_EXPIRED` (HTTP 409); the target box must be `PLANNED`, belong to that member's `ACTIVE` subscription, and still have a free slot (otherwise `ERR_SLOT_CAPACITY_EXCEEDED`, HTTP 422); the held copy must still be `RESERVED` to this same member; and the age gate is re-checked against the copy's catalog item (`ERR_AGE_INCOMPATIBLE`). Acceptance moves the entry `HELD` → `FULFILLED`, clears the entry's `held_copy_id` to null, and creates a box item whose `toy_copy_id` is the held copy, which remains `RESERVED` — now backing the box slot rather than the hold — and the box's `version` increments by one; the response is the updated entry returned with a 200 status.

Holds die in two ways. The operations checkpoint expires any `HELD` entry whose `hold_expires_at` has been reached: the entry becomes `EXPIRED` with its `held_copy_id` cleared to null, its copy is released `RESERVED` → `AVAILABLE` with `reserved_member_id` cleared, and the targeted sweep immediately considers the next eligible waiting entry for that catalog item. A member may also cancel an entry outright while it is `WAITING` or `HELD` — any other state yields `ERR_INVALID_STATE` — and cancelling a `HELD` entry performs the same copy release and re-sweep, likewise clearing `held_copy_id`. In every such release path — expiry, cancellation, pause, subscription cancel, or account closure — a held copy that has since been slotted into a box and still backs a pending item of an open box is left reserved rather than released. `FULFILLED`, `EXPIRED`, and `CANCELLED` are all terminal.

### 3.5. The Rotation Box Cycle: Filling, Swapping, Shipping, and Returning

Creating the next rotation box is the cadence-gated heart of the service. The member's request carries the optimistic-concurrency field of §2.8 and passes two business checks in addition to the state gates: the logical clock must have reached the subscription's `next_cycle_due_at` — an early attempt is rejected with `ERR_BOX_CYCLE_NOT_DUE` (HTTP 422) — and no sibling box of the same subscription may sit in `PLANNED`, `SHIPPED`, `DELIVERED`, `RETURNING`, `RECEIVED`, or `INSPECTED` (`ERR_PREVIOUS_BOX_OPEN`, HTTP 409). Per the validation order of §2.6, the stale-version check is evaluated before these business rules. A legal create stamps the new box `PLANNED` with the next 1-based `cycle_number` in creation order, a `swap_count` of zero, and null `delivered_at`, `due_date`, and `received_at`; the subscription's `version` increments by one. Boxes of a subscription can be listed, and while a box is `DELIVERED` its reads expose `projected_late_fee_cents`, a forward-looking estimate described below; it reads zero in every other state and before the box is late.

Filling a box slots physical copies into it. The member supplies a `toy_copy_id` plus the box-version guard, and the box must still be `PLANNED`. The box's slotted items — those with `loan_status` `PENDING_RETURN` — must number fewer than the plan's `toys_per_box`, or the add fails with `ERR_SLOT_CAPACITY_EXCEEDED`. The copy must be `AVAILABLE`, or already `RESERVED` to this same member; a copy that is anything else — including reserved to a different member — fails with `ERR_COPY_NOT_AVAILABLE` (HTTP 409). Sanitization validity (§2.10) and the developmental age gate (§3.1) both apply. A successful add creates a box item with `loan_status` `PENDING_RETURN`, `resolution_status` `NONE`, `missing_piece_count` zero, `condition_returned` and `damage_severity` null until inspection, the buy-out figures `buyout_price_cents`, `wallet_applied_cents`, and `net_charge_cents` null, and `swapped_from_item_id` null unless the item was created by a swap; the copy moves to `RESERVED` under the caller, and the box's `version` increments by one.

While the box is still `PLANNED`, the member may swap a slotted copy for a different one by naming a `new_toy_copy_id`. Swapping requires the member unsuspended, the item still `PENDING_RETURN` in a `PLANNED` box (otherwise `ERR_INVALID_STATE`), and allowance remaining: the box's `swap_count` must be below the plan's `swap_allowance_per_cycle` — when the count equals the allowance the swap fails with `ERR_SWAP_ALLOWANCE_EXCEEDED` (HTTP 422), so a count one below the allowance marks the last legal swap. The incoming copy faces the same availability-or-self-reserved, sanitization, and age checks as a plain add. A legal swap retires the old item to `SWAPPED_OUT`, creates the replacement item `PENDING_RETURN` with `swapped_from_item_id` pointing at the old item — members and operators can trace an item's swap chain through these links — increments `swap_count` and the box `version`, reserves the new copy, and releases the old copy `RESERVED` → `AVAILABLE`, whose targeted sweep may immediately promote a waiting wishlist entry. The cascade is transitive: swap, copy release, hold promotion.

Shipping is an `OperationsManager` action naming the `carrier` and `tracking_number`. The box must be `PLANNED` and hold at least one `PENDING_RETURN` item — shipping an empty box fails with `ERR_BOX_EMPTY` (HTTP 422). Shipping creates the `OUTBOUND` shipment in `LABEL_CREATED`, moves the box `PLANNED` → `SHIPPED`, and transitions every slotted copy `RESERVED` → `OUT_ON_LOAN`, clearing each `reserved_member_id` since the loan is now tracked through the box items.

Carrier events drive both shipments and boxes. An operator records events with an `event_type` and an `occurred_at` instant, appended in recorded order to the shipment's `events` log. The shipment machine runs `LABEL_CREATED` → `IN_TRANSIT` → (`DELIVERED` | `EXCEPTION` | `LOST_IN_TRANSIT`), with an `EXCEPTION` → `IN_TRANSIT` recovery loop; an event that does not match the shipment's current state is rejected with `ERR_INVALID_STATE`. The `DELIVERED` and `LOST_IN_TRANSIT` events cascade into the box, and the cascade depends on the shipment's `direction`.

On the `OUTBOUND` leg, a `DELIVERED` event recorded while the shipment is `IN_TRANSIT` moves the box `SHIPPED` → `DELIVERED`, stamping `delivered_at` with the event's `occurred_at` and computing `due_date` as that instant plus the plan's `rental_period_days`. While the box is `DELIVERED`, the projected late fee answers "what would the late fee be right now": the whole days between `due_date` and the current logical clock (never below zero), multiplied by 150 cents per day, then capped at the sum of `replacement_value_cents` across the catalog items of every box item whose `loan_status` is `PENDING_RETURN` or `RETURNED` at evaluation time. Because the projection rides the moving clock, it grows daily and typically differs from the fee eventually finalized.

The member starts the return of a `DELIVERED` box — initiating a return from any other state fails with `ERR_INVALID_STATE` — by supplying the return `carrier` and `tracking_number`; this creates the `RETURN` shipment in `LABEL_CREATED` and moves the box `DELIVERED` → `RETURNING`. When the return shipment's `DELIVERED` event lands, the box moves `RETURNING` → `RECEIVED`, `received_at` is stamped with the event instant, every slotted copy moves `OUT_ON_LOAN` → `RETURNED`, and the late fee finalizes: the whole days between `due_date` and `received_at` (never below zero), times 150 cents per day, capped by the same replacement-value sum as the projection. When the finalized fee is positive, a `LATE_RETURN` fee assessment is created in `INVOICED` with a null `box_item_id` — it belongs to the box, not an item — a `FEE_CHARGE` ledger entry for the amount is appended to the member's wallet, and the wallet recompute may trigger the suspension cascade of §2.9. Identical inputs up to the receipt instant can therefore produce a finalized number different from any earlier projection.

A `LOST_IN_TRANSIT` event splits by direction. On the `OUTBOUND` leg, the box — still `SHIPPED` — is cancelled outright: every slotted copy becomes `LOST`, no fees are charged to the member, and the subscription's `next_cycle_due_at` resets to the current clock plus the plan's `rotation_cadence_days` so a replacement cycle can begin. On the `RETURN` leg, the box moves `RETURNING` → `INSPECTED` directly: every item still `PENDING_RETURN` becomes `LOST_REPORTED` with `resolution_status` `FEE_ASSESSED`, a `LOSS` fee at the item's full `replacement_value_cents` is invoiced per item with the accompanying `FEE_CHARGE` ledger append, and every slotted copy becomes `LOST`.

### 3.6. Inspection, Damage Assessment, and Loss Handling

Once a return is `RECEIVED`, an `OperationsManager` inspects the box, submitting an `items` payload with one record per item: the observed `condition_returned` (`GOOD`, `FAIR`, or `WORN`), the `damage_severity` (`NONE`, `MINOR`, `MODERATE`, or `SEVERE`), the `missing_piece_count` (a non-negative integer), and a disposition — `RESTOCK` to return the copy to circulation or `QUARANTINE` to pull it from the rental pool until it is retired. The whole payload is validated before any record is applied, so a rejected call leaves the box untouched: an out-of-range enum or negative piece count yields `ERR_VALIDATION`, a `box_item_id` naming a non-existent item yields `ERR_BOX_ITEM_NOT_FOUND`, one naming an item of a different box yields `ERR_VALIDATION`, and one naming an item no longer `PENDING_RETURN` — already inspected or otherwise resolved — yields `ERR_INVALID_STATE`. Follow-up inspection calls are accepted while the box is `RECEIVED` or already `INSPECTED`, and the box moves `RECEIVED` → `INSPECTED` automatically the moment every `PENDING_RETURN` item has an inspection record; each inspected item's `loan_status` becomes `RETURNED`.

Fees aggregate per item, with the rounding order pinned by §2.7. The damage component is the item's `replacement_value_cents` multiplied by the severity rate — 15% for `MINOR`, 35% for `MODERATE`, 75% for `SEVERE`, and nothing when severity is `NONE` — rounded half up to whole cents. The missing-piece component is `replacement_value_cents` multiplied by the ratio of `missing_piece_count` to the catalog item's `piece_count`, likewise rounded half up, and only when pieces are actually missing. Each component above zero becomes its own fee assessment: `DAMAGE` for the damage component, `MISSING_PIECES` for the missing component. A per-item cap then applies to the pair: when the two components together exceed `replacement_value_cents`, the `MISSING_PIECES` fee is reduced so the two sum exactly to the replacement value — the `DAMAGE` fee ranks first and is never capped. The box-level total is the plain integer sum of the emitted fees with no further rounding. Every emitted fee starts `INVOICED`, appends a `FEE_CHARGE` ledger entry against the member's wallet, and triggers the wallet recompute — suspension toggle included. An item whose inspection produced at least one fee moves its `resolution_status` to `FEE_ASSESSED`; an item with no fees moves straight to `RESOLVED`.

Disposition drives the copy's next chapter. A restocked copy moves `RETURNED` → `SANITIZING`, stamps `sanitization_started_at` with the logical clock, and degrades its `condition_grade` to the worse of its current grade and the recorded `condition_returned`, on the scale where `NEW` beats `GOOD` beats `FAIR` beats `WORN`. A quarantined copy moves `RETURNED` → `QUARANTINED` and leaves the rental pool until retired. Completing sanitization — allowed only while the copy is `SANITIZING` (anything else earns `ERR_INVALID_STATE`) and only after the 24-hour buffer of §2.10 — returns the copy to `AVAILABLE`, stamps `last_sanitized_at` with the clock, increments `sanitization_cycle_count` by one, and fires the targeted allocation sweep for its catalog item. A `PlatformAdmin` may retire a copy while it is `AVAILABLE` or `QUARANTINED`; retiring from any other state fails with `ERR_INVALID_STATE`.

Members can also report a slotted toy lost. The report — which accepts an optional `note` — requires the item still `PENDING_RETURN` and its box in `DELIVERED` or `RETURNING`; otherwise `ERR_INVALID_STATE`. The item becomes `LOST_REPORTED` with `resolution_status` `FEE_ASSESSED`, the copy moves `OUT_ON_LOAN` → `LOST`, and a `LOSS` fee for the full `replacement_value_cents` is invoiced with its `FEE_CHARGE` ledger append and wallet recompute. This mirrors the per-item outcome of the return-leg lost-in-transit cascade.

### 3.7. Keeping a Toy: Buy-Out Pricing and Wallet Application

A member who cannot part with a toy buys it out. The buy-out requires the item `PENDING_RETURN`, its box in `DELIVERED` or `RETURNING`, and the member unsuspended; violations surface as `ERR_INVALID_STATE` or `ERR_MEMBER_SUSPENDED` respectively.

The price builds in four steps. Start with the gross: the catalog item's `retail_value_cents` reduced by the plan's `buyout_discount_pct` fraction. Apply condition depreciation by multiplying the gross by the copy's `condition_grade` at buy-out time — 100% for `NEW`, 85% for `GOOD`, 70% for `FAIR`, 55% for `WORN` — rounding the product half up to whole cents. Compute the rental credit: the whole calendar months between the box's `delivered_at` date and the logical clock date each earn 4% of `retail_value_cents`, the running credit is capped at 30% of `retail_value_cents`, and the capped figure is rounded half up. The price is the depreciated gross minus the rental credit, but never below the 499-cent floor.

Wallet application follows a pinned evaluation order — the dependency only looks circular. The member's `wallet_credit_cents` is read once, at the start of the transaction. The wallet-funded portion `wallet_applied_cents` is the smaller of that balance (floored at zero, so a negative wallet applies nothing) and the price minus 100 cents — at least 100 cents always goes to the card. The remainder `net_charge_cents`, the price minus the wallet portion, is charged to the member's card. All three figures are recorded on the item as `buyout_price_cents`, `wallet_applied_cents`, and `net_charge_cents`. When the wallet portion is positive, a `BUYOUT_CREDIT_APPLIED` ledger entry for its negative amount is appended and the wallet recompute runs, suspension check included. The item moves to `KEPT_BUYOUT` with `resolution_status` `RESOLVED`, and the copy moves `OUT_ON_LOAN` → `SOLD`.

### 3.8. Fees, Settlement, and Disputes

Every financial charge materializes as a fee assessment carrying a `fee_type` of `DAMAGE`, `MISSING_PIECES`, `LOSS`, or `LATE_RETURN`, a positive `amount_cents`, the owning `subscription_id`, the source `rotation_box_id` present for all fee types, and — for every type except `LATE_RETURN` — the source `box_item_id`. Fees open in `INVOICED` and close in `PAID` or `WAIVED`, with a bounded dispute loop in between; `dispute_rounds` counts the cycles consumed. Members and staff can list fees by subscription, by box, or by item, with an optional `status` filter where offered.

Paying is the member's action and names a `payment_source` of `CARD` or `WALLET_CREDIT`. The fee must be `INVOICED`, else `ERR_FEE_NOT_INVOICED` (HTTP 409). A `CARD` payment always succeeds and appends a single `FEE_SETTLED_CARD` entry for the amount. A `WALLET_CREDIT` payment requires `wallet_credit_cents` to cover the full `amount_cents` — anything less fails with `ERR_WALLET_INSUFFICIENT` (HTTP 422) — and appends a pair of entries: `FEE_SETTLED_WALLET` for the amount and `WALLET_DEBIT` for its negative, so the wallet's net movement from settlement is zero beyond the original charge. Either way the wallet recompute runs (suspension toggle included), and when the payment leaves every fee of the owning item in a terminal state, that item's `resolution_status` advances to `RESOLVED`.

A `CustomerService` agent may waive a fee — with an optional `reason` — while it is `INVOICED` or `DISPUTED`, with any other state earning `ERR_FEE_NOT_INVOICED`. Waiving appends a compensating `FEE_WAIVER` entry for the amount (offsetting the original `FEE_CHARGE`), recomputes the wallet, and advances the owning item's resolution as above.

Disputing is the member's escalation, again with an optional `reason`. Only an `INVOICED` fee may be disputed, and only while `dispute_rounds` remains below 2 — a third attempt fails with `ERR_DISPUTE_LIMIT_REACHED` (HTTP 422). A successful dispute moves the fee `INVOICED` → `DISPUTED` and increments `dispute_rounds` by one. Resolution belongs to `CustomerService` and turns on the supplied `outcome`: `UPHELD` returns the fee `DISPUTED` → `INVOICED` with no ledger activity, while `OVERTURNED` waives the fee outright — the same `FEE_WAIVER` append, wallet recompute, and item-resolution advance as a direct waive. Resolving a fee that is not `DISPUTED` fails with `ERR_FEE_NOT_INVOICED`.

Two closure gates lean on fee states. Closing an inspected box is an `OperationsManager` action, `INSPECTED` → `CLOSED`, with any other from-state rejected as `ERR_INVALID_STATE`; it demands every fee tied to the box already `PAID` or `WAIVED`, else `ERR_FEES_OUTSTANDING` (HTTP 422). Closure resets the subscription's `next_cycle_due_at` to the current clock plus the plan's `rotation_cadence_days` and increments the subscription's `version` by one. Member account closure applies the same settled-fees rule across the whole account, as §3.9 describes.

### 3.9. Operations Checkpoint and Account Closure

The allocation checkpoint is an `OperationsManager`-triggered sweep that keeps time-driven state honest, and it does four jobs in one run. It performs a global allocation sweep, promoting eligible `WAITING` entries to `HELD` against every `AVAILABLE`, sanitization-valid copy per the selector rules of §3.4. It expires every `HELD` entry whose `hold_expires_at` has been reached, releasing each held copy and re-sweeping it for the next eligible entry. It activates scheduled pause windows whose start date has arrived — earliest-starting first when several windows of one subscription are due at once — flipping their subscriptions to `PAUSED` with the planned-box cancellation cascade. And it auto-resumes pauses whose `current_pause_end` the clock has reached or passed, closing the windows and shifting each subscription's cadence anchor by the consumed days. The run reports `promoted_count`, `expired_count`, and `resumed_count`, plus the `promoted_entry_ids` of the entries it promoted.

Account closure is the `CustomerService` counterpart for members. Closing a member is allowed from `ACTIVE` or `SUSPENDED` and is gated on a clean account: no rotation box of any of the member's subscriptions may sit in `PLANNED`, `SHIPPED`, `DELIVERED`, `RETURNING`, `RECEIVED`, or `INSPECTED` (`ERR_MEMBER_HAS_OPEN_BOX`, HTTP 409), and no fee of the member may remain `INVOICED` or `DISPUTED` (`ERR_FEES_OUTSTANDING`). Closure moves the member to the terminal `CLOSED` state and cancels every wishlist entry still `WAITING` or `HELD`; each held copy is released `RESERVED` → `AVAILABLE` with `reserved_member_id` cleared, and the targeted sweep re-promotes the next eligible waiting entry for that catalog item.

Support agents also manage wallet goodwill directly. A manual adjustment appends a ledger entry with a signed `amount_cents` — never zero — a `reason` of `PROMO_CREDIT` or `SUPPORT_ADJUSTMENT`, and an optional `note`; the wallet recompute that follows can suspend or restore the member exactly as any other append does. Members and support can page through the resulting ledger history together.

## 4. Endpoint Definitions

Operations that create a new resource — a member, a child profile, a plan, a catalog item, a physical copy, a wishlist entry, a subscription, a rotation box, a box item, a shipment, or a wallet ledger adjustment — return a `201 Created` status code. Operations that modify an existing resource, record an event against one, or drive a state transition return a `200 OK` status code. Request payloads, response fields, preconditions, and side effects are specified in the narratives of §2 and §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/toy-rental/members/register` | Register a new member account | Anonymous |
| GET | `/toy-rental/members/{id}` | Read a member (self or staff) | Member, CustomerService, PlatformAdmin |
| POST | `/toy-rental/members/{id}/close` | Close a member account once boxes and fees are settled | CustomerService |
| POST | `/toy-rental/members/{id}/children` | Add a child profile | Member |
| GET | `/toy-rental/members/{id}/children` | List a member's children | Member, CustomerService |
| POST | `/toy-rental/members/{id}/wallet/adjustments` | Manual wallet adjustment (promo credit or support adjustment) | CustomerService |
| GET | `/toy-rental/members/{id}/wallet/ledger` | List wallet ledger entries | Member, CustomerService |
| GET | `/toy-rental/members/{id}/reserved-copies` | List copies currently RESERVED to this member | Member, OperationsManager |
| POST | `/toy-rental/members/{id}/subscriptions` | Start a subscription on a plan (one non-CANCELLED subscription per member) | Member |
| GET | `/toy-rental/members/{id}/subscriptions` | List a member's subscriptions | Member, CustomerService |
| POST | `/toy-rental/members/{id}/wishlist-entries` | Add a catalog item to the member's wishlist | Member |
| GET | `/toy-rental/members/{id}/wishlist-entries` | List a member's wishlist entries | Member |
| POST | `/toy-rental/subscription-plans` | Create a subscription plan | PlatformAdmin |
| GET | `/toy-rental/subscription-plans` | List plans | Member, CustomerService, PlatformAdmin |
| GET | `/toy-rental/subscription-plans/{id}` | Read a plan | Member, CustomerService, PlatformAdmin |
| GET | `/toy-rental/subscription-plans/{id}/subscriptions` | List subscriptions on a plan | CustomerService, PlatformAdmin |
| GET | `/toy-rental/subscriptions/{id}` | Read a subscription | Member, OperationsManager, CustomerService |
| PATCH | `/toy-rental/subscriptions/{id}/plan` | Change plan (OCC-guarded) | Member |
| POST | `/toy-rental/subscriptions/{id}/pause` | Pause immediately (start_date on or before the clock date) or schedule a future pause window | Member |
| POST | `/toy-rental/subscriptions/{id}/resume` | Resume early from an active pause | Member |
| POST | `/toy-rental/subscriptions/{id}/cancel` | Cancel the subscription (terminal) | Member |
| POST | `/toy-rental/subscriptions/{id}/rotation-boxes` | Create the next rotation box (cadence-due and OCC-guarded) | Member |
| GET | `/toy-rental/subscriptions/{id}/rotation-boxes` | List boxes of a subscription | Member, OperationsManager |
| GET | `/toy-rental/subscriptions/{id}/fees` | List fees of a subscription | Member, CustomerService |
| POST | `/toy-rental/catalog-items` | Create a catalog toy | PlatformAdmin |
| GET | `/toy-rental/catalog-items` | List catalog toys; the `child_id` filter applies the rolling 30-day age variant for suggestions | Member, OperationsManager, PlatformAdmin |
| GET | `/toy-rental/catalog-items/{id}` | Read a catalog toy | Member, OperationsManager, PlatformAdmin |
| POST | `/toy-rental/catalog-items/{id}/retire` | Retire a catalog toy | PlatformAdmin |
| POST | `/toy-rental/catalog-items/{id}/copies` | Mint a physical copy | PlatformAdmin |
| GET | `/toy-rental/catalog-items/{id}/copies` | List copies of a catalog toy | OperationsManager, PlatformAdmin |
| GET | `/toy-rental/catalog-items/{id}/wishlist-entries` | List wishlist demand for a catalog toy | OperationsManager, PlatformAdmin |
| GET | `/toy-rental/copies/{id}` | Read a copy | Member, OperationsManager, PlatformAdmin |
| POST | `/toy-rental/copies/{id}/complete-sanitization` | Finish sanitization after the mandatory 24-hour buffer | OperationsManager |
| POST | `/toy-rental/copies/{id}/retire` | Retire an AVAILABLE or QUARANTINED copy | PlatformAdmin |
| GET | `/toy-rental/copies/{id}/wishlist-entries` | List wishlist entries currently holding this copy | OperationsManager |
| GET | `/toy-rental/copies/{id}/box-items` | List box slots this copy has occupied | OperationsManager |
| POST | `/toy-rental/wishlist-entries/{id}/cancel` | Cancel a WAITING or HELD entry | Member |
| POST | `/toy-rental/wishlist-entries/{id}/accept-hold` | Accept a HELD entry straight into a PLANNED box slot | Member |
| GET | `/toy-rental/rotation-boxes/{id}` | Read a box (includes projected_late_fee_cents while DELIVERED) | Member, OperationsManager |
| POST | `/toy-rental/rotation-boxes/{id}/items` | Add an AVAILABLE or self-RESERVED copy to a PLANNED box (OCC-guarded) | Member |
| GET | `/toy-rental/rotation-boxes/{id}/items` | List box items | Member, OperationsManager |
| POST | `/toy-rental/rotation-boxes/{id}/ship` | Ship a PLANNED box (creates the outbound shipment) | OperationsManager |
| POST | `/toy-rental/rotation-boxes/{id}/initiate-return` | Member starts the return (creates the return shipment) | Member |
| GET | `/toy-rental/rotation-boxes/{id}/shipments` | List shipments of a box | Member, OperationsManager |
| POST | `/toy-rental/rotation-boxes/{id}/inspect` | Record per-item inspection outcomes (condition, damage, missing pieces, disposition) | OperationsManager |
| POST | `/toy-rental/rotation-boxes/{id}/close` | Close an INSPECTED box once all its fees are settled | OperationsManager |
| GET | `/toy-rental/rotation-boxes/{id}/fees` | List fees tied to a box | Member, CustomerService, OperationsManager |
| GET | `/toy-rental/box-items/{id}` | Read a box item | Member, OperationsManager |
| GET | `/toy-rental/box-items/{id}/fees` | List fees tied to a box item | Member, CustomerService |
| GET | `/toy-rental/box-items/{id}/swaps` | List items swapped out in favor of this item's chain (children by swapped_from_item_id) | Member, OperationsManager |
| POST | `/toy-rental/box-items/{id}/swap` | Swap this slotted copy for another while the box is PLANNED | Member |
| POST | `/toy-rental/box-items/{id}/buyout` | Buy out the slotted copy | Member |
| POST | `/toy-rental/box-items/{id}/report-lost` | Member reports the slotted copy lost | Member |
| POST | `/toy-rental/shipments/{id}/events` | Record a carrier event | OperationsManager |
| POST | `/toy-rental/fees/{id}/pay` | Pay an INVOICED fee by card or wallet credit | Member |
| POST | `/toy-rental/fees/{id}/waive` | Waive an INVOICED or DISPUTED fee | CustomerService |
| POST | `/toy-rental/fees/{id}/dispute` | Dispute an INVOICED fee (at most 2 rounds) | Member |
| POST | `/toy-rental/fees/{id}/resolve-dispute` | Resolve a dispute: UPHELD returns to INVOICED, OVERTURNED waives | CustomerService |
| POST | `/toy-rental/ops/allocation-runs` | Ops-run checkpoint: global allocation sweep, hold expiry, scheduled-pause activation, pause auto-resume | OperationsManager |
| POST | `/toy-rental/_clock/set_current_utc` | Set the logical clock (test-driving endpoint; startup default 2026-05-01T00:00:00Z, never wall-clock) | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is an identifier-to-status reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_CATALOG_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_COPY_NOT_FOUND` | 404 Not Found |
| `ERR_WISHLIST_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_BOX_NOT_FOUND` | 404 Not Found |
| `ERR_BOX_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_FEE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MEMBER_SUSPENDED` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_COPY_NOT_AVAILABLE` | 409 Conflict |
| `ERR_FEE_NOT_INVOICED` | 409 Conflict |
| `ERR_HOLD_EXPIRED` | 409 Conflict |
| `ERR_MEMBER_HAS_OPEN_BOX` | 409 Conflict |
| `ERR_PREVIOUS_BOX_OPEN` | 409 Conflict |
| `ERR_AGE_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_NEEDS_RESANITIZATION` | 422 Unprocessable Entity |
| `ERR_BOX_CYCLE_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_PAUSE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SANITIZATION_BUFFER_ACTIVE` | 422 Unprocessable Entity |
| `ERR_EMAIL_TAKEN` | 409 Conflict |
| `ERR_SUBSCRIPTION_ACTIVE_EXISTS` | 409 Conflict |
| `ERR_WISHLIST_DUPLICATE` | 409 Conflict |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SWAP_ALLOWANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PAUSE_ALLOWANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BOX_EMPTY` | 422 Unprocessable Entity |
| `ERR_CATALOG_ITEM_RETIRED` | 422 Unprocessable Entity |
| `ERR_WALLET_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_DISPUTE_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_FEES_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
