# School Picture Day API — Product Requirements Document

## 1. Introduction

School picture day is a deceptively complex operation. A single visit weaves together half a dozen workflows that most schools and studios handle today with paper rosters, spreadsheets, and after-the-fact reconciliation: scheduling photographers and backdrops against homeroom groups, capturing photos and matching each frame back to the right child, publishing an online gallery behind an access code, taking package and print orders from guardians, running retouch and retake-day adjustments against a fixed studio credit, exporting approved frames into the yearbook, shipping prints home, and finally settling the fundraising commission owed back to the school.

This document specifies the School Picture Day API, the backend that orchestrates that entire arc for a Lifetouch-style photography operation. The design separates four cooperating parties — the school-side coordinator, the studio-side photographer, the back-office fulfillment clerk, and the guardian placing orders for a child — and gives each a precise slice of authority over a shared session. The central organizing record is the **picture day session**, a compound posture that gates which child operations are legal at any moment: a roster can only be built before it is locked, photos can only be captured while capture is open, orders can only be placed while the gallery is open, and commission can only be reconciled once ordering has closed.

Two financial mechanisms deserve special mention up front because they shape much of the business logic that follows. First, the school earns a fundraising **commission** on merchandise sold, accrued provisionally as each order is paid and then reconciled to a single authoritative figure when the session settles. Second, the studio works against a fixed **retouch credit budget** for the session; every approved retouch or retake-day request draws that balance down, and cancellations return it. Both balances are derived, reconciled quantities, and the contract below pins exactly how they are computed so that two independent implementations arrive at the same cents.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. All resources are addressed under the `/api` prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 401). When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `SchoolCoordinator`, `StudioPhotographer`, `FulfillmentClerk`, and `Guardian`.

The first three are operator roles whose `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `SchoolCoordinator`, `StudioPhotographer`, or `FulfillmentClerk`, the server treats `X-User-ID` as a free-floating credential: it may be carried for audit purposes, but it is never compared against the `id` of any stored record. These roles are distinguished only by which operations they may invoke, not by ownership of particular rows.

The `Guardian` role is different: its identity is entity-backed by a student. When `X-User-Role` is `Guardian`, `X-User-ID` is the opaque guardian identifier recorded as the `guardian_user_id` of one or more students on a roster. Ownership checks on any resource that references a student compare the resource's owning student back to this identifier. Concretely, when a guardian creates, submits, cancels, or reads an order, or reads their own student record, the server requires that the target student's `guardian_user_id` equals the request's `X-User-ID`; if it does not, the request is rejected with `ERR_NOT_OWNER` (HTTP 403). A guardian may only ever act on orders that belong to a student they own.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Every persisted resource carries a server-minted `id`, which is a UUID used purely for identity — it carries no type prefix and is never supplied by the client. Resources also carry a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits recording when the row was first created.

All entities in this system are full lifecycle records and additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is an ISO 8601 UTC instant refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value when the resource is created and increments by one on every mutation, including mutations to derived fields. Every entity in this specification — picture day sessions, students, photos, package catalog items, photo orders, order lines, retouch orders, shipments, backdrops, photographers, and capture slots — exposes all four common properties.

A critical consequence of `version` semantics for derived ledgers: when a guardian's payment is recorded against an order, the resulting accrual of provisional commission onto the session is itself a mutation of the session, so the session's `version` advances and its `updated_at` refreshes. The same is true whenever a retouch credit is reserved or released, or whenever any computed balance on the session changes. This is the foundation of the optimistic concurrency rule in §2.9.

### 2.5. Session Posture and Hierarchical Consistency

The picture day session's `status` is a compound posture that gates the operations its children allow, moving through `DRAFT`, `ROSTER_LOCKED`, `CAPTURE_OPEN`, `GALLERY_OPEN`, `ORDERING_CLOSED`, and the two terminal states `SETTLED` and `CANCELLED`. Children are not addressed under the session in the URL — every entity is a peer collection under `/api` and references its parents through foreign keys carried in request bodies — but their legality is nonetheless governed by the session's current posture. Matching a photo, marking a student absent, and completing a capture slot require the session to be in `CAPTURE_OPEN`; submitting an order and approving a photo require it to be in `GALLERY_OPEN`; creating a retake-day request requires it to be in either `CAPTURE_OPEN` or `GALLERY_OPEN`.

Several operations mutate more than one entity at once. When a posture transition or a workflow action cascades into child records — cancelling a session, completing a retake, paying an order — the system applies every secondary effect described in §3 atomically, and each affected record independently refreshes its own `updated_at` and increments its own `version`. There is no partial application: either the whole cascade lands or the request is rejected.

For requests that name a resource by its `id` in the path, the server validates that the path resource exists before applying any business rule; a missing path resource yields the matching not-found error (for example `ERR_SESSION_NOT_FOUND`, `ERR_PHOTO_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, and so on through the catalogue in §5). For create operations whose body carries foreign keys, the referenced rows must exist as well — a body naming a missing `picture_day_session_id`, `student_id`, `photo_id`, `photo_order_id`, `package_item_id`, `backdrop_id`, or `photographer_id` is rejected with the corresponding not-found error before any further processing.

### 2.6. Validation Order

When a single request could fail several checks, the system evaluates them in a fixed priority order so that the returned error is deterministic. Authentication comes first: the presence and well-formedness of `X-User-ID` and `X-User-Role` is checked before anything else, then the role's permission for the operation, then — for guardian-scoped order endpoints — the ownership check tying `X-User-ID` to the target student's `guardian_user_id`. After authentication and authorization, the server confirms that any resource named in the path exists, then that any foreign keys in the body reference existing rows. Only then does it apply body-shape validation (required fields present and correctly typed, enum values within their declared sets, and the field-level constraints described in §2.7). After body validation, the server enforces session posture (is the parent session in the right state for this operation), then the target resource's own state (is this order actually `SUBMITTED`, is this photo actually `MATCHED`, and so on). Domain-specific business gates — scheduling overlap, gallery access, the match threshold, shipping prerequisites, retouch credit sufficiency, and the settle-time version check — are evaluated last, after the structural checks have all passed. The effect of this ordering is that, for instance, a forbidden role is always reported as `ERR_FORBIDDEN_ROLE` rather than being masked by a later state or business error.

### 2.7. Field-Level Constraints

Several fields carry constraints that are enforced at create or update time and, when violated, produce `ERR_INVALID_REQUEST` (HTTP 422). A package catalog item's `base_price_cents` must be strictly greater than zero. An order line's `quantity` must be at least 1. A retouch order's `adjustment_count` must be at least 0. A session's `retouch_budget_cents` must be at least 0. A capture slot's `end_minute` must be strictly greater than its `start_minute`, and both `start_minute` and `end_minute` are expressed as minutes-since-midnight on the session's scheduled date, so each must be at least 0. A package item's `sku` must be unique within its session; an attempt to add a second catalog item with a `sku` already present in the same session is likewise rejected with `ERR_INVALID_REQUEST`. The same error covers any missing required body field, any field of the wrong type, and any enum value outside its declared set.

### 2.8. Monetary Precision and Rounding

All monetary quantities in this system are integers denominated in cents — there are no fractional-cent values stored or returned. Wherever a calculation multiplies a money amount by a fractional rate or discount and must collapse the result back to an integer number of cents, the system rounds half up: a value exactly halfway between two integers rounds to the larger magnitude. The precise point at which rounding is applied differs between calculations and is pinned individually in §3; the commission rules in particular are sensitive to whether rounding happens per order or once over a total, and §3.7 spells out both. Match confidence scores are likewise integers in the range 0 through 100, produced by the same round-half-up rule.

### 2.9. Optimistic Concurrency at Settlement

Settling a session is the one operation in this system guarded by optimistic concurrency control, because it reconciles a provisional running balance to an authoritative final value and must be computed against current data. The settle request must carry an `expected_picture_day_session_version` field — it is required, not optional — holding the `version` of the session the client last observed. If that value does not equal the session's current `version`, the settle is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412). This protects against a stale view: because paying or rejecting an order advances the session's `version` (it changes the commission gross), a settle computed from a version captured before such a change would reconcile against an out-of-date figure. Rejecting the stale settle forces the client to re-read the session and reconcile against the true current state. No other endpoint takes a version field; only settlement performs this check.

### 2.10. Logical Clock

The server maintains a logical clock used for all time-sensitive comparisons, in particular the gallery expiry check. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any explicit set it stays at that default rather than falling back to wall-clock time. An operator may advance the clock by supplying a `to_iso8601` instant to the clock-setting capability; from then on, the supplied instant is "now" for the purposes of every server-side time comparison.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Session: Roster, Catalog, and Scheduling Resources

A `SchoolCoordinator` opens the engagement by creating a picture day session, supplying the `school_name`, the `scheduled_date` (the ISO 8601 UTC date the picture day will be held), a `gallery_closes_at` instant after which the gallery access code will stop working, and a `retouch_budget_cents` figure representing the total studio retouch credit allocated for the session. A new session begins life in `DRAFT`. At creation the server initializes the derived ledgers: the remaining retouch credit, exposed as `retouch_credit_balance_cents`, starts equal to `retouch_budget_cents`; the school's running commission, exposed as `school_commission_balance_cents`, starts at zero; and the commission gross, exposed as `total_merchandise_cents`, starts at zero. The `gallery_access_code` and `gallery_opens_at` fields are null at this stage — they are minted only when the gallery opens.

While the session is still in `DRAFT`, the coordinator builds the roster. Each student is added with a `picture_day_session_id` naming the session, a `full_name`, a `grade` label (such as "5"), a `homeroom` label (such as "R-204"), and a `guardian_user_id` identifying the parent who will order for and view this child. Every new student enters as `ENROLLED`. The same draft phase is when the coordinator stocks the package catalog: each catalog item carries a `picture_day_session_id`, a `sku` unique within the session, a display `name` such as "Deluxe Package", a `tier` of `BASIC`, `DELUXE`, or `PREMIUM`, a `base_price_cents` unit price, and an `active` flag (defaulting to true) governing whether the item may be added to new orders.

The coordinator also lays out the day's scheduling resources. A backdrop is registered with a `picture_day_session_id`, a `label` such as "Blue Marble", and an `active` flag defaulting to true that governs whether the backdrop may be booked. A photographer resource is registered with a `picture_day_session_id` and a `full_name`. With backdrops and photographers in place, the coordinator schedules capture slots; slot scheduling and its overlap rules are detailed in §3.2.

Once at least one student exists on the roster, the coordinator locks it, transitioning the session `DRAFT → ROSTER_LOCKED`. Locking with an empty roster is rejected with `ERR_EMPTY_ROSTER`. After the lock, the roster is immutable: no further student may be created against that session. The session's `version` advances by one on the lock.

### 3.2. Scheduling Capture Slots Without Double-Booking

A capture slot reserves a window of the picture day for a homeroom group, occupying one backdrop and one photographer simultaneously. The coordinator creates a slot by supplying a `picture_day_session_id`, the `backdrop_id` and `photographer_id` it occupies, the `homeroom` group scheduled into the window, and the window itself as `start_minute` and `end_minute` (minutes since midnight on the scheduled date). A new slot enters `SCHEDULED`. Each slot also carries a `status` that may later become `COMPLETED` or `CANCELLED`.

The interesting constraint is that a slot's two resources are checked with deliberately different geometry, and only slots currently in `SCHEDULED` on the same session count as occupying. The backdrop is checked first. Two windows on the same `backdrop_id` are treated as half-open intervals: the candidate conflicts with an existing scheduled slot when the candidate's start is earlier than the existing slot's end **and** the existing slot's start is earlier than the candidate's end. Crucially, exact adjacency is permitted — a candidate whose start equals an existing slot's end does not conflict, because a zero-length gap is allowed on a backdrop. Any backdrop conflict is rejected with `ERR_BACKDROP_DOUBLE_BOOKED`.

The photographer is checked second, and only if the backdrop check passes. A photographer needs a mandatory ten-minute buffer between consecutive slots for set changes, so each existing photographer window is inflated by that buffer on both sides before the overlap test. Concretely, for any existing scheduled slot sharing the candidate's `photographer_id`, the candidate conflicts when the candidate's start is earlier than the existing slot's end plus ten minutes **and** the existing slot's start is earlier than the candidate's end plus ten minutes. Two of a photographer's slots must therefore be separated by at least ten minutes of clear gap; exact adjacency, which the backdrop tolerates, is a conflict here. Any photographer conflict is rejected with `ERR_PHOTOGRAPHER_DOUBLE_BOOKED`. Because the backdrop test runs first, a candidate that conflicts on both resources surfaces the backdrop error.

While the session is in `CAPTURE_OPEN`, a `StudioPhotographer` may mark a scheduled slot completed, advancing it `SCHEDULED → COMPLETED`; attempting this when the session is not capturing yields `ERR_SESSION_NOT_CAPTURING`, and attempting it on a slot that is not `SCHEDULED` yields `ERR_SLOT_NOT_SCHEDULED`. A photographer may also cancel a scheduled slot, advancing it `SCHEDULED → CANCELLED` and freeing its backdrop and photographer for that interval; cancelling a slot that is not `SCHEDULED` yields `ERR_SLOT_NOT_CANCELLABLE`.

### 3.3. Capture and Matching

A `StudioPhotographer` opens the shoot. The transition from `ROSTER_LOCKED → CAPTURE_OPEN` requires that the catalog contain at least one item with `active` true; opening capture against an empty or fully-inactive catalog is rejected with `ERR_EMPTY_CATALOG`. The session's `version` advances by one. Once capture is open, photo capture and matching are enabled.

The photographer captures a photo by supplying the `picture_day_session_id` and the slate fields read off the shoot card — `candidate_name`, `candidate_grade`, and `candidate_homeroom`. A freshly captured photo enters `UNMATCHED` with a `match_confidence_score` of 0 and a `yearbook_exported` flag of false; its `matched_student_id` and `retake_of_photo_id` are null until set by later workflow. Each photo also tracks its lifecycle `status` through `UNMATCHED`, `MATCHED`, `RETAKE_REQUESTED`, `RETAKEN`, and the terminal `APPROVED`.

Matching is the act of binding a captured frame to a roster row, and it runs an automatic scorer. Matching requires the session to be in `CAPTURE_OPEN` (otherwise `ERR_SESSION_NOT_CAPTURING`). The candidate set is every student in the photo's session whose `status` is `ENROLLED`. For each such candidate, the scorer compares three normalized signals against the photo's slate fields: whether the student's `full_name` matches the photo's `candidate_name`, whether the student's `grade` matches the photo's `candidate_grade`, and whether the student's `homeroom` matches the photo's `candidate_homeroom`. Each comparison contributes its weight only when it matches: the name comparison is worth half the total, the homeroom comparison three-tenths, and the grade comparison two-tenths. The candidate's score is one hundred times the sum of the weights of its matching signals, rounded half up to a whole number on the 0-to-100 scale. Candidates are ranked by score descending, and ties are broken by `created_at` ascending — the earliest-created student wins a tie, never the `id`.

The winning candidate must clear an auto-match threshold of eighty points. If the candidate set is empty, or the best candidate's score is strictly below eighty, the match is refused with `ERR_NO_MATCH_CANDIDATE`. The boundary is inclusive: a score of exactly eighty auto-matches, while seventy-nine or below does not. (As a worked intuition, a name-and-homeroom match with a grade miss yields one hundred times eight-tenths, which is exactly eighty and matches; a name-only match yields fifty, and a name-and-grade match yields seventy, neither of which clears the bar.) On a successful match, the photo's `matched_student_id` is set to the winning candidate, its `match_confidence_score` is recorded, the photo advances `UNMATCHED → MATCHED`, and the matched student advances `ENROLLED → PHOTOGRAPHED`.

A photographer may also mark a student absent while the session is in `CAPTURE_OPEN`, advancing that student `ENROLLED → ABSENT`. Marking absent requires the session to be capturing (otherwise `ERR_SESSION_NOT_CAPTURING`) and the student to still be `ENROLLED` with no photo yet matched; marking a student who has already been photographed is rejected with `ERR_STUDENT_ALREADY_PHOTOGRAPHED`. `ABSENT` is terminal for a student, as is `PHOTOGRAPHED`.

### 3.4. Opening the Gallery and Guarding Access

When capture is complete, the coordinator opens the online gallery, transitioning the session `CAPTURE_OPEN → GALLERY_OPEN`. Two preconditions guard this step. First, no student may remain `ENROLLED` — every roster row must have reached `PHOTOGRAPHED` or `ABSENT`, or the transition is rejected with `ERR_CAPTURE_INCOMPLETE`. Second, no photo may be sitting in `RETAKE_REQUESTED`; an outstanding retake blocks the gallery with `ERR_RETAKE_PENDING`. On success the server mints the `gallery_access_code` guardians will use, sets `gallery_opens_at` to the current logical clock, enables ordering for guardians, and advances the session's `version` by one.

Gallery viewing is the one read protected by a business gate. A caller fetching the gallery supplies an `access_code` (and may page with `limit` and `offset`). Access is granted only when the supplied `access_code` equals the session's minted `gallery_access_code` **and** the current logical clock is strictly before `gallery_closes_at`. A wrong code, or a request at or after `gallery_closes_at`, is refused with `ERR_GALLERY_ACCESS_DENIED`. The gallery returns the session's `APPROVED` photos.

Approving a photo is the coordinator's act of blessing a frame for the gallery and yearbook. Approval requires the session to be in `GALLERY_OPEN` (otherwise `ERR_SESSION_NOT_GALLERY`) and the photo to be in either `MATCHED` or `RETAKEN` (otherwise `ERR_PHOTO_NOT_APPROVABLE`). A successful approval advances the photo `MATCHED → APPROVED` or `RETAKEN → APPROVED`, after which the photo is eligible for yearbook export.

The coordinator can later export the session's approved frames as a yearbook batch (paged with `limit` and `offset`). The export returns the `APPROVED` photos and, as a side effect, sets `yearbook_exported` to true on each photo it returns, marking that the frame has been included in a yearbook export batch.

### 3.5. Retouch and Retake Day

Retouch and retake-day work is the studio's, and both flow through a single retouch order record drawing on the session's fixed retouch credit. A `StudioPhotographer` creates a retouch order against a photo by supplying the `photo_id`, a `kind` of either `RETOUCH` or `RETAKE`, and an optional `adjustment_count` (defaulting to 0) giving the number of retouch adjustments requested. A new retouch order enters `REQUESTED` and tracks its `status` through `APPROVED`, `DONE`, `REJECTED`, and `CANCELLED`. When the `kind` is `RETAKE`, creating the request also drives the referenced photo `MATCHED → RETAKE_REQUESTED`; this is only legal while the session is in `CAPTURE_OPEN` or `GALLERY_OPEN` (otherwise `ERR_SESSION_NOT_RETAKEABLE`) and only while the photo is `MATCHED` (otherwise `ERR_PHOTO_NOT_RETAKEABLE`).

The cost of the request is fixed at creation time, in a pinned evaluation order so that the complimentary discount can never depend on the credit balance it will later reduce. First, the gross cost, stored as `gross_cost_cents`, is a base retouch fee of 1500 cents plus a per-adjustment fee of 500 cents for each adjustment requested. Second, the system determines `premium_linked`: it is true when the photo's matched student has a photo order that is `PAID` and carries a premium line — that is, an order whose `has_premium_line` flag is true because at least one of its lines references a `PREMIUM`-tier package item. Third, the complimentary discount, stored as `comp_discount_cents`, is half of the gross cost rounded half up when `premium_linked` is true, and zero otherwise. Fourth, the net cost, stored as `net_cost_cents`, is the gross cost minus the complimentary discount. The same fee schedule applies to a `RETAKE`; a retake typically carries an `adjustment_count` of 0, giving a gross of 1500 cents. The balance is not touched at this point — the debit happens later, at approval, after the net cost has been fixed here.

Approval is what reserves the money. Approving a retouch order requires that its `net_cost_cents` be no greater than the session's current `retouch_credit_balance_cents`; if the net cost would exceed the remaining credit, approval is refused with `ERR_INSUFFICIENT_RETOUCH_CREDIT` (HTTP 402). On approval the order advances `REQUESTED → APPROVED` and the session's `retouch_credit_balance_cents` is decreased by the net cost — the credit is reserved. The remaining credit balance is, equivalently, the session's `retouch_budget_cents` minus the sum of `net_cost_cents` over every retouch order in `APPROVED` or `DONE`, and it is recomputed on every retouch mutation.

Completing an approved order advances it `APPROVED → DONE` and finalizes the already-reserved net cost (it stays debited); completing an order that is not `APPROVED` is rejected with `ERR_RETOUCH_NOT_APPROVED`. For a `RETAKE`, completion does more: it drives the linked photo `RETAKE_REQUESTED → RETAKEN`, creates a brand-new replacement photo that is `MATCHED` to the same student and whose `retake_of_photo_id` points back at the photo it supersedes, and records that new photo's id on the retouch order as `replacement_photo_id`.

The two unhappy paths both revert the photo. Rejecting a retouch order is only legal while it is `REQUESTED` (otherwise `ERR_RETOUCH_NOT_REQUESTED`); it advances the order `REQUESTED → REJECTED`, and for a `RETAKE` it reverts the linked photo `RETAKE_REQUESTED → MATCHED`. Cancelling a retouch order is legal while it is `REQUESTED` or `APPROVED` (otherwise `ERR_RETOUCH_NOT_CANCELLABLE`); it advances the order to `CANCELLED`, and if the order was already `APPROVED` it releases the reserved net cost back into `retouch_credit_balance_cents`. As with rejection, cancelling a `RETAKE` reverts the linked photo `RETAKE_REQUESTED → MATCHED`. `DONE`, `REJECTED`, and `CANCELLED` are all terminal for a retouch order.

### 3.6. Ordering: Carts, Lines, and Submission

Ordering belongs to the `Guardian`, who orders only for a student they own. A guardian creates a photo order by supplying the `picture_day_session_id` and the `student_id` it is for; the new order enters `CART` with every money field at zero. A guardian then adds order lines, each carrying the `photo_order_id` it belongs to, the `package_item_id` purchased, and a `quantity`. At the moment a line is added, the system snapshots the package item's `base_price_cents` into the line's `unit_price_cents`, computes the line's `line_total_cents` as the snapshot unit price times the quantity, and recomputes the order's `has_premium_line` flag — which becomes true if any line on the order references a `PREMIUM`-tier package item. A line may only be added while its order is in `CART`; adding to an order that is not `CART` is rejected with `ERR_ORDER_NOT_CART`.

Submission freezes the order and is only legal while the session is in `GALLERY_OPEN` (otherwise `ERR_SESSION_NOT_ORDERING`) and the order has at least one line (otherwise `ERR_EMPTY_ORDER`). Submission advances the order `CART → SUBMITTED` and finalizes its money fields per §3.7. A guardian may cancel an order while it is `CART` or `SUBMITTED`, advancing it to `CANCELLED` and freezing it; cancelling an order in any other state is rejected with `ERR_ORDER_NOT_CANCELLABLE`. `FULFILLED`, `REJECTED`, and `CANCELLED` are the terminal order states.

### 3.7. Order Totals and the School Commission

The order total is computed once, at submission, over all the order lines present at that moment. The subtotal, stored as `subtotal_cents`, is the sum across every line of its `unit_price_cents` times its `quantity`. A volume discount is then selected by the subtotal, with inclusive boundaries: when the subtotal is at least 15000 cents the discount fraction, stored as `discount_pct`, is ten percent; otherwise when the subtotal is at least 5000 cents it is five percent; otherwise it is zero. The boundary is inclusive, so a subtotal of exactly 5000 cents earns the five-percent tier while 4999 earns nothing. The discount amount, stored as `discount_cents`, is the subtotal times the discount fraction, rounded half up — and it is the single subtotal-level discount that is rounded, never the individual lines. The merchandise amount, stored as `merchandise_cents`, is the subtotal minus the discount; this is the commission base and deliberately excludes shipping. Shipping, stored as `shipping_cents`, is free (zero) when the merchandise amount is at least 10000 cents and otherwise a flat 599 cents. The amount due, stored as `total_cents`, is the merchandise amount plus shipping.

The school's fundraising commission accrues against merchandise, never shipping, and it is computed twice over the life of a session: provisionally as each order is paid, and definitively when the session settles. Both variants share one tiered rate function of a gross merchandise figure: the rate is twenty-five percent when the gross is at least 150000 cents, twenty percent when the gross is at least 50000 cents but below 150000, and otherwise fifteen percent. The two variants differ in what gross they key off and where they round, and the difference is the heart of the reconciliation.

The **provisional** commission is accrued one order at a time, in payment chronological order, when a `FulfillmentClerk` records payment on a submitted order. Paying an order requires it to be `SUBMITTED` (otherwise `ERR_ORDER_NOT_SUBMITTED`) and advances it `SUBMITTED → PAID`. At that moment the running gross is the session's `total_merchandise_cents` as it stood before this order — the sum of `merchandise_cents` over all orders already in `PAID` or `FULFILLED`. The order's own `merchandise_cents` is added to that running gross to give a new cumulative gross, and the commission rate is taken from the tier of that new cumulative gross. This order's commission line is its own `merchandise_cents` times that rate, rounded half up, and that rounded line is added to the session's `school_commission_balance_cents`. Each paid order is thus rounded individually and then summed — round-per-order-then-sum. Recording the payment also adds the order's `merchandise_cents` to the session's `total_merchandise_cents`. A clerk may instead reject a submitted order, advancing it `SUBMITTED → REJECTED` and freezing it with no commission accrued; rejecting an order that is not `SUBMITTED` is likewise `ERR_ORDER_NOT_SUBMITTED`.

The **final** commission is recomputed once, at settlement, over a single total. The total gross is the sum of `merchandise_cents` across every order in `PAID` or `FULFILLED` at settle time. A single final rate is taken from the tier of that total gross, the final commission is the total gross times that single rate rounded half up exactly once over the whole total — sum-then-round, not round-per-order — and the session's `school_commission_balance_cents` is set to that final figure. The reconciliation delta is the final commission minus whatever provisional balance had accrued, and applying it brings the provisional running balance into exact agreement with the authoritative final figure. After settlement the balance equals the total gross times the final rate, rounded half up, exactly. The two methods can disagree precisely because chronological per-order rounding and rate selection differ from one rounding at one rate over the whole.

### 3.8. Payment, Shipping, and Distribution

Fulfillment is the `FulfillmentClerk`'s domain. Once an order is `PAID`, the clerk creates a shipment to carry the prints to the family, supplying the `photo_order_id` being distributed, a `carrier` name, a `distribution_method` of either `SCHOOL_PICKUP` or `HOME_DELIVERY`, and an optional `tracking_code`. A new shipment enters `PENDING` and tracks its `status` through `DISPATCHED`, `DELIVERED`, and `VOIDED`. While a shipment is still `PENDING`, the clerk may update its `carrier`, `distribution_method`, or `tracking_code`; these edits are permitted only in `PENDING`.

Dispatching a shipment carries it `PENDING → DISPATCHED` and, as a cross-entity side effect, drives the linked order `PAID → FULFILLED`. Dispatch has two preconditions: the linked order must be `PAID` (otherwise `ERR_ORDER_NOT_PAID`) and the shipment must already carry a `tracking_code` (otherwise `ERR_TRACKING_REQUIRED`). From there the clerk may mark the shipment delivered, advancing it `DISPATCHED → DELIVERED`; delivering a shipment that is not `DISPATCHED` is rejected with `ERR_SHIPMENT_NOT_DISPATCHED`. Alternatively, while a shipment is still `PENDING`, the clerk may void it, advancing it `PENDING → VOIDED`; voiding a shipment that is not `PENDING` is rejected with `ERR_SHIPMENT_NOT_VOIDABLE`. `DELIVERED` and `VOIDED` are terminal for a shipment.

### 3.9. Closing Out: Ordering Close, Settlement, and Cancellation

When the ordering window has run its course, the coordinator closes ordering, advancing the session `GALLERY_OPEN → ORDERING_CLOSED` and advancing its `version` by one. This is only legal once no order for the session is still `SUBMITTED` — every submitted order must have reached `PAID` or `REJECTED` first — and an outstanding submitted order blocks the close with `ERR_OPEN_ORDERS_EXIST`. After ordering closes, no new order may be created or submitted for the session.

Settlement is the terminal accounting act. The coordinator settles a closed session, advancing it `ORDERING_CLOSED → SETTLED` and advancing its `version` by one. Settlement carries the `expected_picture_day_session_version` and is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412) when that value does not equal the session's current `version`, exactly as described in §2.9. Beyond the version check, settlement requires that every order in `PAID` for the session have a shipment that is not `VOIDED`; a paid order with no live shipment blocks settlement with `ERR_UNSHIPPED_ORDERS`. On success, settlement recomputes the final commission over all `PAID` and `FULFILLED` orders and reconciles `school_commission_balance_cents` from its provisional value to that final value, applying the reconciliation delta as described in §3.7.

A session may be cancelled, but only from `DRAFT`, `ROSTER_LOCKED`, or `CAPTURE_OPEN`, and only when no order for the session is `PAID` or `FULFILLED`; an existing paid or fulfilled order blocks cancellation with `ERR_PAID_ORDERS_EXIST`. Cancellation is a cascade: every retouch order for the session's photos that is in `REQUESTED` or `APPROVED` is moved to `CANCELLED`, and any that were `APPROVED` release their reserved `net_cost_cents` back into the session's `retouch_credit_balance_cents`; every capture slot still in `SCHEDULED` is moved to `CANCELLED`; and the session's `version` advances by one. `SETTLED` and `CANCELLED` are the terminal session states. (An attempt to drive any session lifecycle transition from a state that does not permit it is reported as `ERR_INVALID_SESSION_TRANSITION`.)

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all the lifecycle transitions driven by the action endpoints — return a `200 OK` status code. Read operations also return `200 OK`. Request bodies, response shapes, and side effects for each endpoint are specified in the §3 narratives above; the table below lists only the routing and authorization contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/picture-day-sessions` | Create a picture day session | SchoolCoordinator |
| GET | `/api/picture-day-sessions` | List sessions | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| GET | `/api/picture-day-sessions/{id}` | Get a session (includes computed ledgers) | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| POST | `/api/picture-day-sessions/{id}/lock-roster` | Lock the roster | SchoolCoordinator |
| POST | `/api/picture-day-sessions/{id}/open-capture` | Open photo capture | StudioPhotographer |
| POST | `/api/picture-day-sessions/{id}/open-gallery` | Open the online gallery and mint the access code | SchoolCoordinator |
| POST | `/api/picture-day-sessions/{id}/close-ordering` | Close ordering | SchoolCoordinator |
| POST | `/api/picture-day-sessions/{id}/settle` | Settle the session and reconcile commission | SchoolCoordinator |
| POST | `/api/picture-day-sessions/{id}/cancel` | Cancel the session | SchoolCoordinator |
| GET | `/api/picture-day-sessions/{id}/gallery` | View the gallery of approved photos using the access code | Guardian, SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| GET | `/api/picture-day-sessions/{id}/yearbook-export` | Export approved photos as a yearbook batch | SchoolCoordinator |
| POST | `/api/students` | Add a student to a session roster | SchoolCoordinator |
| GET | `/api/students` | List students (filter by session) | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| GET | `/api/students/{id}` | Get a student | SchoolCoordinator, StudioPhotographer, FulfillmentClerk, Guardian |
| POST | `/api/students/{id}/mark-absent` | Mark a student absent | StudioPhotographer |
| POST | `/api/packages` | Add a package/print catalog item | SchoolCoordinator |
| GET | `/api/packages` | List catalog items (filter by session/active) | SchoolCoordinator, StudioPhotographer, FulfillmentClerk, Guardian |
| GET | `/api/packages/{id}` | Get a catalog item | SchoolCoordinator, StudioPhotographer, FulfillmentClerk, Guardian |
| POST | `/api/backdrops` | Add a backdrop resource | SchoolCoordinator |
| GET | `/api/backdrops` | List backdrops (filter by session) | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| GET | `/api/backdrops/{id}` | Get a backdrop | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| POST | `/api/photographers` | Add a photographer resource | SchoolCoordinator |
| GET | `/api/photographers` | List photographers (filter by session) | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| GET | `/api/photographers/{id}` | Get a photographer | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| POST | `/api/capture-slots` | Schedule a capture slot (overlap-checked) | SchoolCoordinator |
| GET | `/api/capture-slots` | List capture slots (filter by session/backdrop/photographer) | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| GET | `/api/capture-slots/{id}` | Get a capture slot | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| POST | `/api/capture-slots/{id}/complete` | Mark a capture slot completed | StudioPhotographer |
| POST | `/api/capture-slots/{id}/cancel` | Cancel a scheduled capture slot | StudioPhotographer |
| POST | `/api/photos` | Capture a photo with slate candidate fields | StudioPhotographer |
| GET | `/api/photos` | List photos (filter by session, matched student, retake lineage, status) | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |
| GET | `/api/photos/{id}` | Get a photo | SchoolCoordinator, StudioPhotographer, FulfillmentClerk, Guardian |
| POST | `/api/photos/{id}/match` | Auto-match a captured photo to a student | StudioPhotographer |
| POST | `/api/photos/{id}/approve` | Approve a photo for gallery/yearbook | SchoolCoordinator |
| POST | `/api/photo-orders` | Create an order (CART) for a student | Guardian |
| GET | `/api/photo-orders` | List orders (filter by session/student/status) | SchoolCoordinator, FulfillmentClerk, Guardian |
| GET | `/api/photo-orders/{id}` | Get an order | SchoolCoordinator, FulfillmentClerk, Guardian |
| POST | `/api/order-lines` | Add a line item to a CART order | Guardian |
| GET | `/api/order-lines` | List line items (filter by order or package item) | SchoolCoordinator, FulfillmentClerk, Guardian |
| GET | `/api/order-lines/{id}` | Get an order line | SchoolCoordinator, FulfillmentClerk, Guardian |
| POST | `/api/photo-orders/{id}/submit` | Submit a cart order; freezes totals | Guardian |
| POST | `/api/photo-orders/{id}/pay` | Record payment on a submitted order | FulfillmentClerk |
| POST | `/api/photo-orders/{id}/reject` | Reject a submitted order | FulfillmentClerk |
| POST | `/api/photo-orders/{id}/cancel` | Cancel a CART or SUBMITTED order | Guardian |
| POST | `/api/retouch-orders` | Create a retouch or retake-day request against a photo | StudioPhotographer |
| GET | `/api/retouch-orders` | List retouch orders (filter by photo, replacement photo, or status) | SchoolCoordinator, StudioPhotographer |
| GET | `/api/retouch-orders/{id}` | Get a retouch order | SchoolCoordinator, StudioPhotographer |
| POST | `/api/retouch-orders/{id}/approve` | Approve a retouch order (reserves credit) | StudioPhotographer |
| POST | `/api/retouch-orders/{id}/complete` | Complete an approved retouch/retake | StudioPhotographer |
| POST | `/api/retouch-orders/{id}/reject` | Reject a requested retouch order | StudioPhotographer |
| POST | `/api/retouch-orders/{id}/cancel` | Cancel a requested/approved retouch order | StudioPhotographer |
| POST | `/api/shipments` | Create a shipment for a PAID order | FulfillmentClerk |
| GET | `/api/shipments` | List shipments (filter by order/status) | SchoolCoordinator, FulfillmentClerk |
| GET | `/api/shipments/{id}` | Get a shipment | SchoolCoordinator, FulfillmentClerk |
| PUT | `/api/shipments/{id}` | Update a PENDING shipment (e.g. set tracking_code) | FulfillmentClerk |
| POST | `/api/shipments/{id}/dispatch` | Dispatch a shipment (fulfills the order) | FulfillmentClerk |
| POST | `/api/shipments/{id}/deliver` | Mark a shipment delivered | FulfillmentClerk |
| POST | `/api/shipments/{id}/void` | Void a pending shipment | FulfillmentClerk |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock | SchoolCoordinator, StudioPhotographer, FulfillmentClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_PHOTO_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_RETOUCH_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BACKDROP_NOT_FOUND` | 404 Not Found |
| `ERR_PHOTOGRAPHER_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_EMPTY_ROSTER` | 409 Conflict |
| `ERR_EMPTY_CATALOG` | 409 Conflict |
| `ERR_CAPTURE_INCOMPLETE` | 409 Conflict |
| `ERR_RETAKE_PENDING` | 409 Conflict |
| `ERR_OPEN_ORDERS_EXIST` | 409 Conflict |
| `ERR_UNSHIPPED_ORDERS` | 409 Conflict |
| `ERR_PAID_ORDERS_EXIST` | 409 Conflict |
| `ERR_SESSION_NOT_CAPTURING` | 409 Conflict |
| `ERR_SESSION_NOT_ORDERING` | 409 Conflict |
| `ERR_SESSION_NOT_GALLERY` | 409 Conflict |
| `ERR_SESSION_NOT_RETAKEABLE` | 409 Conflict |
| `ERR_INVALID_SESSION_TRANSITION` | 409 Conflict |
| `ERR_STUDENT_ALREADY_PHOTOGRAPHED` | 409 Conflict |
| `ERR_PHOTO_NOT_RETAKEABLE` | 409 Conflict |
| `ERR_PHOTO_NOT_APPROVABLE` | 409 Conflict |
| `ERR_ORDER_NOT_SUBMITTED` | 409 Conflict |
| `ERR_ORDER_NOT_PAID` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_CART` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 409 Conflict |
| `ERR_RETOUCH_NOT_APPROVED` | 409 Conflict |
| `ERR_RETOUCH_NOT_REQUESTED` | 409 Conflict |
| `ERR_RETOUCH_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_DISPATCHED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_VOIDABLE` | 409 Conflict |
| `ERR_TRACKING_REQUIRED` | 409 Conflict |
| `ERR_SLOT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_SLOT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_NO_MATCH_CANDIDATE` | 422 Unprocessable Entity |
| `ERR_GALLERY_ACCESS_DENIED` | 403 Forbidden |
| `ERR_INSUFFICIENT_RETOUCH_CREDIT` | 402 Payment Required |
| `ERR_BACKDROP_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_STALE_SESSION_VERSION` | 412 Precondition Failed |
