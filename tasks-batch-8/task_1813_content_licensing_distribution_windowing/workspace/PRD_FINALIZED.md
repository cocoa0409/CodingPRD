# Content Licensing Windowing API — Product Requirements Document

## 1. Introduction

Studios that license film and television catalogs to streaming and transactional platforms operate under a deceptively simple constraint: every title can only be sold once per window, per territory, per language, and what was sold yesterday constrains what may be sold tomorrow. Exclusivity granted to one platform locks the same cell of inventory for every other buyer. Holdback rules push availability of downstream windows out by weeks or months after an upstream exclusive ends. Expiration dates on the studio's own rights — the window during which the studio is even allowed to sell — close independently of any deal. Without a single system tracking these overlapping temporal intervals, distribution executives routinely double-book inventory, miss contracted takedowns, and under-recoup minimum guarantees.

This document specifies the Content Licensing Windowing API, a studio-distribution platform that manages the full lifecycle from rights inventory through royalty payout. The system tracks **rights slots** (a title crossed with territory, language, and window type), packages them into **avail offers** addressed to specific buyer platforms, converts accepted offers into **license agreements** with flat-fee, revenue-share, or minimum-guarantee economics, and reconciles platform-reported revenue through a recoupment waterfall into per-holder royalty statements. A logical clock drives all time-based behavior — offers expire, licenses terminate, takedown notices execute, and slots lapse — making every temporal rule deterministic and testable.

The API serves four roles with deliberately segregated duties: the `RightsManager` runs the catalog and deal lifecycle, the `PlatformBuyer` accepts offers and reports usage revenue, the `FinanceAnalyst` builds and finalizes royalty statements and reverses erroneous reports, and the `FinanceController` — who must never be the same individual as the finalizer — marks statements paid.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the acting user, and `X-User-Role` names the role under which they act. Four roles exist, spelled exactly as follows: `RightsManager`, `PlatformBuyer`, `FinanceAnalyst`, `FinanceController`.

When `X-User-Role` is `PlatformBuyer`, `X-User-ID` is the `id` of the acting `Platform`; ownership checks on any resource that references a `Platform` compare the resource's foreign-key field to `X-User-ID`. A `PlatformBuyer` may accept or decline only packages addressed to their own platform, may submit revenue reports only against licenses whose `platform_id` equals their own id, and sees only their own records on the buyer-visible list endpoints — if a `platform_id` filter is supplied on such a list it must equal the caller's own id, and when it is omitted the list defaults to the caller's own platform.

When `X-User-Role` is `RightsManager`, `FinanceAnalyst`, or `FinanceController`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `finalized_by_user_id` on a `RoyaltyStatement` when a `FinanceAnalyst` finalizes, or as `paid_by_user_id` when a `FinanceController` marks paid) but does not compare it to any entity's `id`.

A request missing either header, or carrying an `X-User-Role` value outside the four declared roles, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is not listed for the endpoint — including a `PlatformBuyer` attempting to act on a package or license addressed to a different platform — is rejected with `ERR_FORBIDDEN` (403). The authentication check runs first; the authorization and ownership check runs second, before any body validation.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0, minimum 0). Results are sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every entity in the system carries four server-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. `version` is an integer that increments by exactly one on every mutation of the resource, including mutations caused by cascading side effects. All entities in this system — `Title`, `RightsHolder`, `Platform`, `RightsSlot`, `AvailPackage`, `LicenseAgreement`, `DeliveryBatch`, `TakedownNotice`, `RevenueReport`, `RoyaltyStatement` — carry all four common fields.

### 2.5. The Logical Clock and the Expiration Sweep

All time-dependent behavior in the system keys off a **logical clock**, never wall-clock time. At server startup, before any client has advanced it, the logical clock reads exactly `2026-08-01T00:00:00Z`. The clock advances when an authorized operator (`RightsManager`, `FinanceAnalyst`, or `FinanceController`) invokes the clock-advance capability with a target instant supplied as `to_iso8601`. The clock is monotonic: a target earlier than the current logical clock is rejected with `ERR_CLOCK_REGRESSION` (422).

Advancing the clock synchronously runs the **expiration sweep**, which processes expirations in a pinned order; within each step, entities are processed in `created_at` ascending order (never by `id`). The expiry rule is uniform: a resource expires when the logical clock is greater than or equal to its end instant — intervals are half-open, so at exactly the end instant the resource is expired.

1. **Slots first.** Every `RightsSlot` in `AVAILABLE` or `ENCUMBERED` whose `sellable_to` is at or before the new clock value moves to `EXPIRED`. When an `ENCUMBERED` slot expires, the rights-lapse cascade fires: every `EXECUTED` or `ACTIVE` license on that slot moves to `TERMINATED`, each such license's termination credit is computed normally per its `proration_mode` with the termination instant equal to the sweep time, and each terminated license's `SCHEDULED` takedown notice moves to `EXECUTED` with `executed_at` set to the sweep time. After slot expirations settle, blocked-line propagation and all-blocked package expiry run as described in §3.4.
2. **Licenses second.** Every `LicenseAgreement` in `EXECUTED` or `ACTIVE` whose `license_end` is at or before the new clock value moves to `EXPIRED`; each such license's `SCHEDULED` notice moves to `EXECUTED`; and each expired exclusive license triggers slot-encumbrance re-evaluation followed by the line-unblock cascade on offered packages.
3. **Packages third.** Every `AvailPackage` in `OFFERED` whose `offer_expires_at` is at or before the new clock value moves to `EXPIRED`, and all of its non-`LICENSED` lines move to `NOT_SELECTED`.

The clock-advance response reports the new clock value as `current_utc` alongside sweep tallies: `slots_expired`, `licenses_expired`, `licenses_terminated`, `packages_expired`, and `notices_executed`.

### 2.6. Monetary Precision and Rounding

All monetary quantities are integer cents. Every division and percentage application in this system — revenue-share accrual, volume-discount computation, per-line discount allocation, termination proration, and holder-level royalty due — rounds **half up to integer cents** at the step where the scaffold of the calculation specifies. Two rounding disciplines recur: per-report royalty accrual rounds once at submission, and statements sum those already-rounded integers rather than recomputing from gross; the holder's due amount is then rounded exactly once, at the end.

### 2.7. Optimistic Concurrency Control on License Agreements

Two write operations on a `LicenseAgreement` are guarded by optimistic concurrency control: submitting a revenue report against a license, and extending a license. Both requests must carry `expected_license_version`, a non-optional field equal to the license's current `version` as last observed by the client. If the value does not match the license's current `version` — because another booked report or a prior extension has advanced the version since the client last read the license — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Each legitimately successful revenue-report booking mutates `recouped_cents`, `royalty_payable_cents`, and `outstanding_recoupment_cents` and advances the license's `version` by one, so a client holding a stale view would otherwise compute recoupment from superseded state. Each extension moves `license_end` and re-schedules the takedown notice, so a client extending from a stale read would silently build on a superseded window. No other endpoint in the system accepts a version field.

### 2.8. Temporal Interval Semantics: Half-Open versus Closed-and-Buffered

Two interval conventions coexist, and confusing them produces real double-bookings. **Same-cell exclusivity overlap** uses half-open semantics: two licenses on the same title, territory, language, and window type conflict when the existing license's `license_start` is strictly before the candidate's `license_end`, and the candidate's `license_start` is strictly before the existing license's `license_end`, and at least one of the two is exclusive. Adjacent windows — where the candidate's start equals the existing license's end — do not conflict. **Cross-window holdback blocking** uses a closed, buffered interval: an exclusive license on a window with a non-empty holdback row blocks a candidate license on a blocked downstream window whenever the candidate's `license_start` is on or before the upstream license's `holdback_until` and the candidate's `license_end` is on or after the upstream license's `license_start`. The holdback rule applies regardless of whether the candidate itself is exclusive.

### 2.9. Validation Order and Resource Existence

When multiple validations could reject the same request, the server evaluates them in a fixed priority order. Authentication (headers present, role known) runs first, then authorization and platform ownership, then request-body schema validation (required fields present, types correct, enum values known — including the rule that any window or period end is strictly after its start), then existence of every referenced resource, then state checks, then business-safety rules (embargo, segregation of duties), then business-referential rules (line membership, duplicate line slots), then business-temporal rules (window containment, clock monotonicity), then business-constraint rules (duplicate slot tuples, exclusivity and holdback conflicts, blocked lines, empty acceptance, statement period overlap, delivery completeness), and finally business-fiscal rules (positive revenue, fee-structure consistency).

Referenced resources are validated for existence left to right — path identifiers first, then body identifiers in declaration order. Each resource type has its own not-found error: `ERR_TITLE_NOT_FOUND`, `ERR_HOLDER_NOT_FOUND`, `ERR_PLATFORM_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, and `ERR_STATEMENT_NOT_FOUND`, all 404. A malformed body is rejected with `ERR_INVALID_REQUEST` (400).

### 2.10. Embedded Package Lines

An `AvailPackage` does not reference a separate line resource; its `lines` are embedded in the package document itself. Each line carries the offered terms for one slot: the input sub-fields `slot_id`, `license_start`, `license_end`, `exclusive`, `fee_model`, and conditionally `flat_fee_cents`, `revenue_share_pct`, `minimum_guarantee_cents`, and `proration_mode`; plus two computed sub-fields, `line_status` (one of `PENDING`, `OFFERED`, `BLOCKED`, `LICENSED`, `NOT_SELECTED`; initially `PENDING`) and `created_license_id` (null until the line is accepted). Within one package, `slot_id` values must be distinct — two lines referencing the same slot are rejected with `ERR_DUPLICATE_LINE_SLOT` (422). A package must contain at least one line.

## 3. Business Logic & Workflows

### 3.1. Catalog Registration: Titles, Rights Holders, and Platforms

Before any inventory can be sold, a `RightsManager` registers the catalog. A `Title` carries a unique `title_code`, a display `name`, a `content_type` of either `FILM` or `SERIES`, the `original_language` as an ISO-639 code, the `production_year`, and an optional `embargoed_territories` array — ISO-3166 alpha-2 codes where the title may never be licensed, defaulting to empty. Titles can be listed with an optional `content_type` filter.

A `RightsHolder` is the royalty payee: a legal `name`, an accounts-payable `payee_reference`, and a `royalty_share_pct` expressing the percentage of studio net royalty payable to this holder on statements. The share must be greater than 0 and at most 100; a holder registered with a share outside that range is rejected with `ERR_FEE_STRUCTURE_INVALID` (422).

A `Platform` is a buyer: a display `name`, a `platform_type` of `SVOD`, `AVOD`, `TVOD`, or `EST`, the `metadata_spec_version` the platform ingests (for example MEC-2.3 — every delivery to this platform must match it), and `required_asset_profiles`, the asset profile tags every delivery batch must include, with at least one profile required. Platforms can be listed with an optional `platform_type` filter; `PlatformBuyer` callers may read the platform catalog.

### 3.2. Building the Rights Inventory

A `RightsSlot` is one sellable cell of inventory: a title crossed with a territory, a language, and a window type. The `RightsManager` creates a slot by supplying `title_id`, `rights_holder_id`, `territory_code`, `language_code`, `window_type` (one of `THEATRICAL`, `EST`, `TVOD`, `SVOD`, `AVOD`, `FREE_TV`), and the rights period the studio owns, from `sellable_from` (inclusive) to `sellable_to` (exclusive). The end must be strictly after the start. The slot's `slot_status` begins at `AVAILABLE`.

Three guards protect inventory integrity at creation. First, compliance: if the slot's territory appears in its title's `embargoed_territories`, creation is rejected with `ERR_TERRITORY_EMBARGOED` (422). Second, uniqueness: the tuple of `title_id`, `territory_code`, `language_code`, and `window_type` must be unique among slots whose `slot_status` is `AVAILABLE` or `ENCUMBERED`; a clash is rejected with `ERR_DUPLICATE_SLOT` (409). Once a slot leaves those states — by being withdrawn or expiring — its tuple becomes available again. Third, the referenced title and rights holder must exist. Slots can be searched with optional filters on `title_id`, `rights_holder_id`, `slot_status`, `territory_code`, and `window_type`.

A `RightsManager` may pull a slot from the market by withdrawing it, which is permitted only while the slot is `AVAILABLE`; attempting to withdraw a slot in any other state is rejected with `ERR_SLOT_NOT_WITHDRAWABLE` (409). Withdrawal moves the slot to `WITHDRAWN` and fires the blocked-line cascade described in §3.4.

### 3.3. Packaging Avails and Sending the Offer

To sell inventory, a `RightsManager` assembles an `AvailPackage` addressed to one buyer platform. The package carries the target `platform_id`, an offer `name`, an `offer_expires_at` instant after which the offer lapses, and at least one line of proposed terms as described in §2.10. At creation the server computes `guaranteed_total_cents` as the sum over **all** lines of guaranteed value: a `FLAT_FEE` line contributes its `flat_fee_cents`, a `MINIMUM_GUARANTEE` line contributes its `minimum_guarantee_cents`, and a `REVENUE_SHARE` line contributes zero. This total is computed once at creation and is immutable thereafter. The fields `discount_pct`, `discount_cents`, and `net_total_cents` are null until acceptance, and `offered_at` is null until the package is sent. The package's `package_status` begins at `DRAFT`.

Fee structure is validated per line (and per direct license) against the line's `fee_model`. A `FLAT_FEE` line requires `flat_fee_cents` greater than 0 and forbids `revenue_share_pct` or `minimum_guarantee_cents` above 0. A `REVENUE_SHARE` line requires `revenue_share_pct` greater than 0 and at most 100. A `MINIMUM_GUARANTEE` line requires `minimum_guarantee_cents` greater than 0 and `revenue_share_pct` greater than 0 and at most 100. Any inconsistency is rejected with `ERR_FEE_STRUCTURE_INVALID`. Fee fields not required by the model default to 0, and `proration_mode` defaults to `DAILY_PRORATION`.

Sending the offer — a `RightsManager` action that moves the package from `DRAFT` to `OFFERED` — re-validates the whole package against live inventory. The package must currently be `DRAFT`, otherwise `ERR_PACKAGE_NOT_DRAFT` (409). Every line's slot must exist and be `AVAILABLE`, otherwise `ERR_SLOT_NOT_AVAILABLE` (409). Every line's window must be contained in its slot's rights period — `license_start` at or after `sellable_from` and `license_end` at or before `sellable_to` — otherwise `ERR_WINDOW_OUTSIDE_RIGHTS` (422). No line may create an exclusivity or holdback conflict against `EXECUTED` or `ACTIVE` licenses, nor may two lines of the same package conflict with each other; violations surface as `ERR_EXCLUSIVITY_CONFLICT` or `ERR_HOLDBACK_CONFLICT` (both 409). Finally, `offer_expires_at` must be strictly after the logical clock at offer time, otherwise `ERR_OFFER_WINDOW_PAST` (422). On success every line moves from `PENDING` to `OFFERED` and `offered_at` is set to the logical clock.

A `RightsManager` may pull a package back while it is `DRAFT` or `OFFERED`; withdrawing moves it to `WITHDRAWN` and moves its non-`LICENSED` lines to `NOT_SELECTED`. A package in any terminal state resists withdrawal with `ERR_PACKAGE_NOT_WITHDRAWABLE` (409).

### 3.4. Encumbrance, Blocking, and the Cross-Package Cascade

Exclusivity is enforced system-wide, across packages, by a cascade that propagates through three hops. When an exclusive license comes into existence on a slot — whether by direct deal or by package acceptance — the slot moves from `AVAILABLE` to `ENCUMBERED`. The transition is idempotent when the slot is already `ENCUMBERED` from another exclusive license. Then hop 1: every line referencing that slot inside any package currently `OFFERED` moves to `BLOCKED` — except lines on the very package being accepted, which move to `LICENSED` instead. Hop 2: an `OFFERED` package whose every line is now `BLOCKED` has nothing sellable left, so the package itself moves to `EXPIRED`. Hop 3: when a package transitions to `EXPIRED`, all of its non-`LICENSED` lines move to `NOT_SELECTED`.

The same cascade fires on slot withdrawal and on slot expiry: offered lines on the affected slot become `BLOCKED`, all-blocked offered packages expire, and their non-`LICENSED` lines become `NOT_SELECTED`.

Release runs in the opposite direction. When an exclusive license on a slot becomes `EXPIRED` or `TERMINATED` and no other `EXECUTED` or `ACTIVE` exclusive license still references the slot — and the slot itself is not already `EXPIRED` or `WITHDRAWN`, since slot expiry dominates — the slot returns from `ENCUMBERED` to `AVAILABLE`. Then the unblock hop: lines referencing that slot with `line_status` `BLOCKED` inside packages still `OFFERED` return to `OFFERED`.

The conflict rules that decide whether a new license may come into existence were introduced in §2.8. The same-cell check applies to licenses sharing title (through the slot), territory, language, and window type, ignoring `EXPIRED` and `TERMINATED` licenses; it fires `ERR_EXCLUSIVITY_CONFLICT`. The cross-window check derives from the holdback matrix: an exclusive `THEATRICAL` license blocks `EST`, `TVOD`, `SVOD`, `AVOD`, and `FREE_TV` candidates for 90 days beyond its `license_end`; an exclusive `EST` license blocks `SVOD`, `AVOD`, and `FREE_TV` for 60 days; an exclusive `TVOD` license blocks `SVOD`, `AVOD`, and `FREE_TV` for 30 days; an exclusive `SVOD` license blocks `AVOD` and `FREE_TV` for 30 days; exclusive `AVOD` and `FREE_TV` licenses block nothing cross-window. When the row is empty the license's `holdback_until` is null; otherwise `holdback_until` is the license's `license_end` plus the row's buffer in days, and any candidate on a blocked window whose interval intersects the closed interval from the upstream `license_start` through `holdback_until` is rejected with `ERR_HOLDBACK_CONFLICT`.

### 3.5. Acceptance: Converting an Offer into Licenses

Acceptance is the `PlatformBuyer`'s action, and only the buyer to whom the package is addressed may perform it — a caller whose `X-User-ID` does not equal the package's `platform_id` is rejected with `ERR_FORBIDDEN`. The package must be `OFFERED`, otherwise `ERR_PACKAGE_NOT_OFFERED` (409); this single check also rejects packages that have already expired or been withdrawn.

The buyer supplies `accepted_slot_ids`. The list must be non-empty, otherwise `ERR_EMPTY_ACCEPTANCE` (422). Every element must be the `slot_id` of some line of the addressed package, otherwise `ERR_LINE_NOT_IN_PACKAGE` (422). Every accepted line must currently have `line_status` `OFFERED` — a `BLOCKED` line cannot be accepted and yields `ERR_LINE_BLOCKED` (409). The accepted lines are then re-validated against live state: each window must still be contained in its slot's rights period, and exclusivity plus holdback conflicts are checked against `EXECUTED` and `ACTIVE` licenses and pairwise within the accepted set.

When `accepted_slot_ids` covers every line, the package moves to `ACCEPTED`; when it covers a strict subset, the package moves to `PARTIALLY_ACCEPTED`. Both transitions share the same side effects. The **volume discount** runs over the accepted lines only, in a pinned evaluation order that keys the tier on the gross guaranteed total, never on the net:

1. The gross is the sum of guaranteed value over accepted lines — `flat_fee_cents` for a `FLAT_FEE` line, `minimum_guarantee_cents` for a `MINIMUM_GUARANTEE` line, zero for a `REVENUE_SHARE` line.
2. The `discount_pct` is tiered on that gross, with each boundary inclusive: a gross of at least 5,000,000 cents earns 15 percent; at least 2,000,000 cents earns 10 percent; at least 500,000 cents earns 5 percent; anything below earns 0.
3. `discount_cents` is the gross multiplied by the discount percentage and divided by 100, rounded half up to integer cents.
4. The discount is allocated across accepted lines: each line's share is `discount_cents` multiplied by the line's guaranteed value and divided by the gross, rounded half up to integer cents; lines with zero guaranteed value receive zero discount.
5. The remainder — `discount_cents` minus the sum of the per-line allocations — is added to the accepted line with the lowest array index among lines whose guaranteed value is greater than zero. This choice is deterministic, never random.
6. Each accepted line's `allocated_fee_cents` is its guaranteed value minus its per-line discount share (minus the remainder for the chosen line).
7. `net_total_cents` is the gross minus `discount_cents`.

The package stores `discount_pct`, `discount_cents`, and `net_total_cents`. One `LicenseAgreement` is created per accepted line, in `EXECUTED` status, with terms copied from the line and `package_id` set to the originating package. Accepted lines move to `LICENSED` with `created_license_id` set; non-accepted lines move to `NOT_SELECTED`. One `TakedownNotice` is auto-created per created license, `SCHEDULED` at that license's `license_end`. For each accepted line with `exclusive` set to true, its slot moves to `ENCUMBERED` and the three-hop cross-package cascade of §3.4 runs.

The buyer may instead decline the offer outright; declining requires the package to be `OFFERED` and the caller to own it, and moves the package to `DECLINED` with its non-`LICENSED` lines becoming `NOT_SELECTED`.

### 3.6. The License Lifecycle

A license comes into existence in one of two ways: through package acceptance (above), or as a **direct deal** created by a `RightsManager` against a slot with no package involved. Direct creation takes `slot_id`, `platform_id`, `license_start`, `license_end`, `exclusive`, `fee_model`, the conditional fee fields, and an optional `proration_mode`. The slot must not be `WITHDRAWN` or `EXPIRED` — an `ENCUMBERED` slot is allowed, because the conflict rules are what decide — otherwise the create is rejected with `ERR_SLOT_NOT_AVAILABLE`. Window containment, exclusivity, and holdback rules apply exactly as at package offer. For a direct deal `package_id` is null and `allocated_fee_cents` equals the input guaranteed fee — `flat_fee_cents` for `FLAT_FEE`, `minimum_guarantee_cents` for `MINIMUM_GUARANTEE`, and 0 for `REVENUE_SHARE`. In both creation paths the license denormalizes `territory_code`, `language_code`, and `window_type` from its slot for conflict queries; an exclusive license derives `holdback_until` per §3.4; a `TakedownNotice` is created `SCHEDULED` at `license_end`; and the recoupment ledger fields — `recouped_cents`, `royalty_payable_cents` — start at 0, with `outstanding_recoupment_cents` equal to the outstanding guarantee for a `MINIMUM_GUarantee` license and 0 otherwise. The license's `license_status` begins at `EXECUTED`, with `activated_at` null and `termination_credit_cents` null.

**Activation** gates revenue-bearing life. A `RightsManager` activates an `EXECUTED` license once two preconditions hold, and the license must be `EXECUTED` at all, otherwise `ERR_LICENSE_NOT_EXECUTABLE` (409). The logical clock must have reached `license_start`, otherwise `ERR_LICENSE_NOT_STARTED` (422). And there must exist a `DeliveryBatch` for this license with `delivery_status` `DELIVERED`, otherwise `ERR_DELIVERY_INCOMPLETE` (422). Activation moves the license to `ACTIVE` and stamps `activated_at` with the logical clock.

**Extension** lengthens the window. A `RightsManager` may extend a license only while it is `EXECUTED` or `ACTIVE`, otherwise `ERR_LICENSE_NOT_EXTENDABLE` (409). The request carries `new_license_end` and — per §2.7 — `expected_license_version`; a stale version is rejected with `ERR_STALE_VERSION` (412). The new end must be strictly after the current `license_end` and at or before the slot's `sellable_to`; containment and both conflict checks are re-validated, with violations surfacing as `ERR_WINDOW_OUTSIDE_RIGHTS`, `ERR_EXCLUSIVITY_CONFLICT`, or `ERR_HOLDBACK_CONFLICT`. On success `license_end` is replaced, `holdback_until` is recomputed, the license's `SCHEDULED` takedown notice moves to `CANCELLED`, and a replacement notice is created `SCHEDULED` at the new end.

**Termination** ends the license early. Termination is permitted from `EXECUTED` or `ACTIVE`; attempting it on an `EXPIRED` or `TERMINATED` license is rejected with `ERR_LICENSE_ALREADY_TERMINAL` (409). Termination fires several effects in one request. The license's `SCHEDULED` notice executes immediately, with `executed_at` set to the logical clock — early termination means immediate takedown. If the license was exclusive and no other `EXECUTED` or `ACTIVE` exclusive license references the slot, the slot moves from `ENCUMBERED` back to `AVAILABLE`, and the line-unblock cascade restores `BLOCKED` lines on `OFFERED` packages to `OFFERED`. And a prorated **termination credit** is computed with the termination instant equal to the logical clock, using whole days (days are seconds floored to 86,400-second units). The credit basis is `allocated_fee_cents` — the post-discount fee, which is 0 for `REVENUE_SHARE` licenses. Under `DAILY_PRORATION`, the credit is the credit basis multiplied by the ratio of remaining seconds to total seconds — where remaining seconds is the greater of zero and `license_end` minus the termination instant, and total seconds is the greater of one and `license_end` minus `license_start` — rounded half up to integer cents. Under `MONTHLY_PRORATION`, the credit is the credit basis multiplied by the ratio of whole remaining 30-day blocks to the total number of 30-day blocks rounded up — that is, remaining days floored to blocks of 30 divided by total days ceiled to blocks of 30 — rounded half up to integer cents, and the credit is 0 whenever the remaining days contain no whole 30-day block.

**Expiry** arrives via the sweep when the logical clock reaches `license_end`: the license moves from `EXECUTED` or `ACTIVE` to `EXPIRED`, its `SCHEDULED` notice executes, and exclusive licenses trigger slot re-evaluation followed by the unblock cascade, exactly as at termination.

### 3.7. Delivering Assets to Platform Spec

Before activation, the studio must actually deliver content. A `RightsManager` queues a `DeliveryBatch` for a license by supplying `license_id`, an `asset_manifest` of at least one asset profile tag, and the `metadata_spec_version` used for this delivery. The batch begins in `QUEUED` with `attempt_count` 0 and both `submitted_at` and `delivered_at` null.

Submitting the batch runs the platform spec check synchronously. The manifest must cover the licensee platform's `required_asset_profiles`, and the batch's `metadata_spec_version` must equal the platform's `metadata_spec_version`. On a pass, the batch moves to `DELIVERED`, `missing_profiles` is set to empty, `attempt_count` increments by one, and both `submitted_at` and `delivered_at` are stamped with the logical clock. On a failure — one or more required profiles absent, or a metadata spec mismatch — the batch moves to `REJECTED`, `missing_profiles` lists exactly the required profiles absent from the manifest, `attempt_count` increments by one, and `submitted_at` is stamped. Only a `QUEUED` batch may be submitted; attempting to submit a batch in any other state is rejected with `ERR_BATCH_INVALID_STATE` (409).

A rejected batch is not dead. Resubmission — allowed only from `REJECTED`, with `DELIVERED` terminal and any other state rejected with `ERR_BATCH_INVALID_STATE` — replaces `asset_manifest` and `metadata_spec_version` with the request values, resets `missing_profiles` to empty, and returns the batch to `QUEUED`. The intended cycle is `QUEUED` to `REJECTED` to `QUEUED` and then, on a successful submit, to `DELIVERED`; there is deliberately no direct `REJECTED`-to-`DELIVERED` shortcut. Batches can be listed with optional `license_id` and `delivery_status` filters, and `PlatformBuyer` callers may read batches for their own licenses.

### 3.8. Revenue Reports and the Recoupment Waterfall

Once a license is live, the platform reports usage revenue. Only the `PlatformBuyer` who owns the license may submit, and the license must be `EXECUTED` or `ACTIVE` with a `fee_model` other than `FLAT_FEE` — flat-fee deals have no revenue share to report — otherwise the submission is rejected with `ERR_LICENSE_NOT_REPORTABLE` (409). Per §2.7 the request carries `expected_license_version`; a mismatch with the license's current `version` is rejected with `ERR_STALE_VERSION` (412).

The report supplies `period_start`, `period_end`, and `gross_revenue_cents`. The period end must be strictly after the period start and must not lie in the future relative to the logical clock — future-dated revenue is rejected with `ERR_REPORT_PERIOD_FUTURE` (422). Gross revenue must be greater than 0, otherwise `ERR_NONPOSITIVE_REVENUE` (422). The `period_end` is treated as inclusive for statement attribution overlap, even though license windows are half-open.

Each accepted report books through the **recoupment waterfall**. The accrued royalty is the gross multiplied by `revenue_share_pct` and divided by 100, rounded half up to integer cents, and stored as `royalty_accrued_cents`. For a `MINIMUM_GUARANTEE` license, the recoupment applied — `recoupment_applied_cents` — is the smaller of the accrued amount and the outstanding recoupment balance immediately before this report; for a `REVENUE_SHARE` license the applied amount is 0. The payable portion, `payable_cents`, is the accrued amount minus the applied amount. In the same request the license's ledger updates: `recouped_cents` increases by the applied amount, `royalty_payable_cents` increases by the payable amount, `outstanding_recoupment_cents` becomes the greater of zero and `minimum_guarantee_cents` minus `recouped_cents`, and the license's `version` advances by one. The report is stored with `license_id` taken from the path, `report_status` `SUBMITTED`, and `submitted_at` stamped with the logical clock — the timestamp that `BY_REPORT_DATE` statement attribution later uses.

A `FinanceAnalyst` may reverse an erroneous report. Only a `SUBMITTED` report can be reversed — `REVERSED` is terminal and a second reversal is impossible. Reversal recomputes the license's `recouped_cents`, `royalty_payable_cents`, and `outstanding_recoupment_cents` from scratch: both cumulative fields are reset to zero, then the waterfall is replayed over the license's remaining `SUBMITTED` reports in chronological order — `submitted_at` ascending, ties broken by `created_at` ascending — and the license's `version` increments with `updated_at` refreshed. Reports can be listed with optional `license_id` and `report_status` filters.

### 3.9. Royalty Statements and Segregation of Duties

Royalty statements settle the studio's obligation to each rights holder. A `FinanceAnalyst` creates a statement in `DRAFT` by supplying `rights_holder_id`, `period_start`, `period_end`, and `attribution_mode`. The period end must be strictly after the period start, and the period — treated as a closed interval, both ends inclusive — must not overlap any other `DRAFT` or `FINALIZED` statement of the same holder; `PAID` statements do not block. An overlap is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (409).

**Attribution** decides which revenue reports fall into the period, following the foreign-key path from each report's `license_id` through the license's `slot_id` to the slot's `rights_holder_id`: only `SUBMITTED` reports whose license's slot belongs to the statement's holder are candidates. Under `BY_REPORT_DATE`, a report is included when its `submitted_at` falls inside the closed interval from `period_start` to `period_end`, both ends inclusive. Under `BY_USAGE_PERIOD`, a report is included when its usage period intersects the statement period — the report's `period_start` at or before the statement's `period_end` and the report's `period_end` at or after the statement's `period_start`.

The statement's totals are computed at creation and again at finalization. `included_report_ids` lists the ids of the in-scope reports. `gross_revenue_cents` is the sum of `gross_revenue_cents` over included reports. `studio_net_royalty_cents` is the sum of `payable_cents` over included reports — the per-report values were already rounded to integer cents at submission, and the statement sums those integers, never recomputing from summed gross. `holder_royalty_due_cents` is the studio net royalty multiplied by the holder's `royalty_share_pct` and divided by 100, rounded half up to integer cents — holder-level rounding applied exactly once, at the end.

Finalization is a `FinanceAnalyst` action on a `DRAFT` statement — any other state is rejected with `ERR_STATEMENT_NOT_DRAFT` (409). Finalizing recomputes the totals as a fresh snapshot, stamps `finalized_by_user_id` with the caller's `X-User-ID`, and makes the statement immutable: reports booked later do not change a `FINALIZED` or `PAID` statement.

Payment is reserved for the `FinanceController`. Marking paid requires the statement to be `FINALIZED`, otherwise `ERR_STATEMENT_NOT_FINALIZED` (409), and enforces segregation of duties: the caller's `X-User-ID` must differ from `finalized_by_user_id` — the same individual who finalized a statement may not mark it paid, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). On success `paid_by_user_id` records the controller and the statement reaches its terminal `PAID` state. Statements can be listed with optional `rights_holder_id` and `statement_status` filters.

### 3.10. Takedown Notices

Takedown notices are a read-only surface for clients; the system creates, executes, and cancels them. Every license creation auto-creates one notice with `notice_status` `SCHEDULED` and `scheduled_for` equal to the license's current `license_end`. When a license expires under the sweep or is terminated early, its `SCHEDULED` notice moves to `EXECUTED` with `executed_at` set to the logical clock. When a license is extended, its `SCHEDULED` notice moves to `CANCELLED` and a replacement notice is created `SCHEDULED` at the new end. Notices can be listed with optional `license_id` and `notice_status` filters and fetched individually by `RightsManager` and `PlatformBuyer` callers.

## 4. Endpoint Definitions

All endpoints are mounted under `/licensing`. Endpoints that create a new resource return 201; endpoints that modify an existing resource, and all read endpoints, return 200. Every response uses the envelope of §2.2; list responses are paginated per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /licensing/_clock/set_current_utc | Advance the logical clock and run the expiration sweep synchronously | RightsManager, FinanceAnalyst, FinanceController |
| POST | /licensing/titles | Register a title | RightsManager |
| GET | /licensing/titles | List titles | RightsManager, FinanceAnalyst, FinanceController |
| GET | /licensing/titles/{id} | Get one title | RightsManager, FinanceAnalyst, FinanceController |
| POST | /licensing/rights-holders | Register a rights holder | RightsManager |
| GET | /licensing/rights-holders | List rights holders | RightsManager, FinanceAnalyst, FinanceController |
| GET | /licensing/rights-holders/{id} | Get one rights holder | RightsManager, FinanceAnalyst, FinanceController |
| POST | /licensing/platforms | Register a buyer platform with its delivery spec | RightsManager |
| GET | /licensing/platforms | List platforms | RightsManager, FinanceAnalyst, FinanceController, PlatformBuyer |
| GET | /licensing/platforms/{id} | Get one platform | RightsManager, FinanceAnalyst, FinanceController, PlatformBuyer |
| POST | /licensing/rights-slots | Create a rights inventory slot | RightsManager |
| GET | /licensing/rights-slots | List rights slots (avail search) | RightsManager, FinanceAnalyst, FinanceController |
| GET | /licensing/rights-slots/{id} | Get one rights slot | RightsManager, FinanceAnalyst, FinanceController |
| POST | /licensing/rights-slots/{id}/withdraw | Withdraw an AVAILABLE slot | RightsManager |
| POST | /licensing/avail-packages | Assemble an avail package addressed to a platform | RightsManager |
| GET | /licensing/avail-packages | List avail packages (buyers see only their own) | RightsManager, PlatformBuyer |
| GET | /licensing/avail-packages/{id} | Get one avail package | RightsManager, PlatformBuyer |
| POST | /licensing/avail-packages/{id}/offer | Send a DRAFT package to the platform | RightsManager |
| POST | /licensing/avail-packages/{id}/accept | Accept all or a subset of offered slots; creates licenses | PlatformBuyer |
| POST | /licensing/avail-packages/{id}/decline | Decline the offer | PlatformBuyer |
| POST | /licensing/avail-packages/{id}/withdraw | Pull a DRAFT or OFFERED package | RightsManager |
| POST | /licensing/license-agreements | Direct deal: create a license against a slot | RightsManager |
| GET | /licensing/license-agreements | List licenses (buyers restricted to own platform) | RightsManager, PlatformBuyer, FinanceAnalyst, FinanceController |
| GET | /licensing/license-agreements/{id} | Get one license | RightsManager, PlatformBuyer, FinanceAnalyst, FinanceController |
| POST | /licensing/license-agreements/{id}/activate | Activate an EXECUTED license | RightsManager |
| POST | /licensing/license-agreements/{id}/extend | Extend license_end (OCC-guarded) | RightsManager |
| POST | /licensing/license-agreements/{id}/terminate | Early termination with prorated credit | RightsManager |
| POST | /licensing/license-agreements/{id}/revenue-reports | Submit usage revenue for a period (OCC-guarded) | PlatformBuyer |
| GET | /licensing/revenue-reports | List revenue reports | RightsManager, PlatformBuyer, FinanceAnalyst, FinanceController |
| GET | /licensing/revenue-reports/{id} | Get one revenue report | RightsManager, PlatformBuyer, FinanceAnalyst, FinanceController |
| POST | /licensing/revenue-reports/{id}/reverse | Reverse a submitted report and recompute the license ledger | FinanceAnalyst |
| POST | /licensing/delivery-batches | Queue a delivery batch for a license | RightsManager |
| GET | /licensing/delivery-batches | List delivery batches | RightsManager, PlatformBuyer |
| GET | /licensing/delivery-batches/{id} | Get one delivery batch | RightsManager, PlatformBuyer |
| POST | /licensing/delivery-batches/{id}/submit | Run the platform spec check synchronously | RightsManager |
| POST | /licensing/delivery-batches/{id}/resubmit | Replace a REJECTED batch's manifest and re-queue it | RightsManager |
| GET | /licensing/takedown-notices | List takedown notices | RightsManager, PlatformBuyer |
| GET | /licensing/takedown-notices/{id} | Get one takedown notice | RightsManager, PlatformBuyer |
| POST | /licensing/royalty-statements | Create a DRAFT royalty statement for a holder and period | FinanceAnalyst |
| GET | /licensing/royalty-statements | List royalty statements | FinanceAnalyst, FinanceController |
| GET | /licensing/royalty-statements/{id} | Get one royalty statement | FinanceAnalyst, FinanceController |
| POST | /licensing/royalty-statements/{id}/finalize | Finalize a DRAFT statement | FinanceAnalyst |
| POST | /licensing/royalty-statements/{id}/mark-paid | Mark a FINALIZED statement paid | FinanceController |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narrative of §2 and §3; this table is the canonical id-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_TITLE_NOT_FOUND | 404 |
| ERR_HOLDER_NOT_FOUND | 404 |
| ERR_PLATFORM_NOT_FOUND | 404 |
| ERR_SLOT_NOT_FOUND | 404 |
| ERR_PACKAGE_NOT_FOUND | 404 |
| ERR_LICENSE_NOT_FOUND | 404 |
| ERR_BATCH_NOT_FOUND | 404 |
| ERR_NOTICE_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_STATEMENT_NOT_FOUND | 404 |
| ERR_TERRITORY_EMBARGOED | 422 |
| ERR_DUPLICATE_SLOT | 409 |
| ERR_SLOT_NOT_WITHDRAWABLE | 409 |
| ERR_SLOT_NOT_AVAILABLE | 409 |
| ERR_PACKAGE_NOT_DRAFT | 409 |
| ERR_PACKAGE_NOT_OFFERED | 409 |
| ERR_PACKAGE_NOT_WITHDRAWABLE | 409 |
| ERR_LINE_NOT_IN_PACKAGE | 422 |
| ERR_DUPLICATE_LINE_SLOT | 422 |
| ERR_EMPTY_ACCEPTANCE | 422 |
| ERR_LINE_BLOCKED | 409 |
| ERR_WINDOW_OUTSIDE_RIGHTS | 422 |
| ERR_EXCLUSIVITY_CONFLICT | 409 |
| ERR_HOLDBACK_CONFLICT | 409 |
| ERR_LICENSE_NOT_EXECUTABLE | 409 |
| ERR_LICENSE_NOT_STARTED | 422 |
| ERR_LICENSE_NOT_EXTENDABLE | 409 |
| ERR_LICENSE_ALREADY_TERMINAL | 409 |
| ERR_LICENSE_NOT_REPORTABLE | 409 |
| ERR_DELIVERY_INCOMPLETE | 422 |
| ERR_NONPOSITIVE_REVENUE | 422 |
| ERR_REPORT_PERIOD_FUTURE | 422 |
| ERR_FEE_STRUCTURE_INVALID | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_BATCH_INVALID_STATE | 409 |
| ERR_STATEMENT_PERIOD_OVERLAP | 409 |
| ERR_STATEMENT_NOT_DRAFT | 409 |
| ERR_STATEMENT_NOT_FINALIZED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_OFFER_WINDOW_PAST | 422 |
| ERR_CLOCK_REGRESSION | 422 |
