# Tanning & Spray-Tan Salon API — Product Requirements Document

## 1. Introduction

This document specifies the back-office and member-facing platform for a Palm Beach Tan–style tanning and spray-tan salon. The salon operates two distinct service lines on a shared schedule: ultraviolet (UV) tanning on physical beds and booths, and sunless spray tanning in ventilated rooms. Members subscribe to recurring, EFT-billed membership tiers — including unlimited plans — and may freeze, unfreeze, upgrade, or cancel those memberships, with prorated credits and charges computed against a fixed thirty-day billing cycle.

The platform's hardest obligations are regulatory rather than commercial. UV exposure is governed by FDA-style dose schedules keyed to a member's Fitzpatrick skin type, by escalation rules that lengthen permitted exposure only as a member accumulates completed sessions, by mandatory cool-down periods between sessions, and by stricter frequency caps for minors that override anything a membership plan would otherwise allow. Equipment must be taken out of service for maintenance after a fixed number of sessions, and every bed, booth, and spray room enforces a turnaround buffer before it can be booked again. Layered on top are a retail line for tanning products, a salon-wide financial ledger that must stay internally consistent as freeze credits are issued and reversed, and optimistic concurrency protection so that two membership changes never silently overwrite one another.

The remainder of this document defines the global request/response contract and cross-cutting principles (Section 2), the detailed business workflows and their scattered rules (Section 3), the endpoint summary (Section 4), and the consolidated error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity in which that principal acts. The system recognizes exactly four roles, spelled precisely as follows: `Member`, `FrontDeskStaff`, `SalonManager`, and `BillingSystem`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_HEADERS`. When the headers are present but the role is not permitted to perform the requested operation — or a `Member` attempts to act on a membership that is not its own — the request is rejected with `ERR_FORBIDDEN`.

The four roles bind to identity in two different ways. When `X-User-Role` is `Member`, the `X-User-ID` is the `id` of the acting `Member` entity; ownership checks on any resource that references a member compare that resource's member foreign key (for example, the `member_id` on a session or a retail order, or the path member identifier on a membership operation) to `X-User-ID`. A `Member` may therefore freeze, unfreeze, upgrade, or cancel only its own membership, book or cancel only its own sessions, and place retail orders only under its own member id; any cross-member attempt yields `ERR_FORBIDDEN`. When `X-User-Role` is `FrontDeskStaff`, `SalonManager`, or `BillingSystem`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`. These three operator roles are not constrained by member-ownership checks within the operations they are authorized for.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless a specific endpoint states otherwise, every list is sorted by the `created_at` timestamp in ascending order. List responses surface `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Common Resource Properties and Audit Fields

Most resources are mutable, audit-tracked entities and carry a uniform system-managed quartet: an `id` that is a server-minted UUID with no type prefix and serves as identity only; a `created_at` ISO 8601 UTC timestamp with three fractional digits stamped at creation; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and a `version` integer that starts at its initial value and increments by one on each mutation. This quartet applies to `Member`, `Equipment`, `SprayRoom`, `Session`, `Product`, `RetailOrder`, and `SalonLedger`.

A few resources are write-once records that carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field, because they are never modified after creation. These are `MembershipPlan`, `ConsentRecord`, `Payment`, and `MaintenanceLog`. Implementers must not synthesize `updated_at` or `version` on these four.

### 2.5. Money, Time, and Rounding

All monetary amounts in this system are integer cents, never fractional currency. Where a calculation must convert a monthly figure into a daily figure, the division is rounded half up to the nearest whole cent before any further multiplication; the resulting credits and charges are then exact integer cents requiring no further rounding. Retail line math also rounds half up to whole cents, applied per line before the lines are summed (see Section 3.7). Counts and durations are integers: UV exposure allowances are whole seconds with no rounding, and session counts are whole numbers.

Time is governed exclusively by a logical clock, never the wall clock. On server startup the logical clock reads `2026-01-01T00:00:00Z`, and it never falls back to real time. An administrative test-driving capability can advance or set the logical clock to a supplied `to_iso8601` instant, returning the new `now`. Every deadline, cool-down window, billing cycle boundary, consent-expiry check, and minor-classification computation reads this logical clock. Booking intervals are half-open: a session occupies `[start_at, end_at)`, where `end_at` equals `start_at` plus `requested_seconds`, so an interval that begins exactly where a prior interval (including its buffer) ends does not overlap.

### 2.6. Parallel State Dimensions and Cascading Side Effects

A `Member` carries two independent state dimensions that evolve in parallel: a lifecycle `status` (one of `PENDING`, `ACTIVE`, `FROZEN`, `CANCELLED`) and a `billing_status` (one of `CURRENT`, `PAST_DUE`, `SUSPENDED`, defaulting to `CURRENT`). The two never collapse into one another; a member can be `ACTIVE` while `PAST_DUE`, for instance. `Session` status (`RESERVED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`, `NO_SHOW`) is deliberately cyclic at the reservation stage: cancelling or no-showing a `RESERVED` session frees its slot so a brand-new `RESERVED` session may reuse the same interval. `Equipment` status (`AVAILABLE`, `IN_USE`, `MAINTENANCE`, `RETIRED`) and `SprayRoom` status (the same four values) are guarded availability lifecycles.

Many operations mutate more than one entity in a single atomic step. Completing a UV session, for example, simultaneously advances the session, the equipment, the member's completed-session counter, and possibly the equipment's maintenance state. Issuing or reversing a freeze credit touches both the member's credit balance and the salon ledger. Each such cascade is specified in full in Section 3; whenever a resource's fields change, its `updated_at` is refreshed and — for the audit-tracked entities of Section 2.4 — its `version` is incremented by one. Several membership transitions increment `Member.version` explicitly as part of their contract, as detailed below.

### 2.7. Nested Resource Retrieval and Existence Ordering

Some collections hang off a parent member or a parent equipment unit — consent records under a member, maintenance logs under an equipment unit, and the like. For any request that names resources in its path or body, the server validates existence left to right: the member is resolved before any equipment, spray room, session, plan, product, or order referenced by the same request. The first identifier that does not resolve produces the corresponding not-found error — `ERR_MEMBER_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND` — before any deeper validation runs. A product reference inside a retail order line that does not resolve likewise yields `ERR_PRODUCT_NOT_FOUND`.

### 2.8. Validation Ordering

When several checks guard a single endpoint, they are evaluated in a fixed precedence so that the same input always produces the same error. The global order is: first, authentication header presence and well-formedness (`ERR_MISSING_AUTH_HEADERS`, HTTP 401); second, role authorization including member-ownership (`ERR_FORBIDDEN`, HTTP 403); third, existence of every referenced resource, left to right (the 404 family above); fourth, request-body shape — required fields present, enum values in range, `requested_seconds` at least 1, and UV-versus-spray consistency (`ERR_INVALID_REQUEST`, HTTP 422); fifth, the target resource being in the correct state for the requested transition (the 409 state family: `ERR_MEMBER_NOT_ACTIVE`, `ERR_MEMBER_NOT_FROZEN`, `ERR_SESSION_NOT_RESERVED`, `ERR_SESSION_NOT_IN_PROGRESS`, `ERR_EQUIPMENT_UNAVAILABLE`, `ERR_ROOM_UNAVAILABLE`, `ERR_ORDER_ALREADY_REFUNDED`). Only after these foundational checks pass does an endpoint run its domain-specific business rules. Within session creation specifically, the booking-eligibility, safety, dose, frequency, and slot-conflict checks follow the strict order laid out in Section 3.4.

### 2.9. Optimistic Concurrency Control on Membership Changes

A member's membership can be changed by several operations, and to prevent one change from silently overwriting another, the membership-mutating operations require the client to pin the `Member.version` it last observed via the field `expected_member_version`. The freeze, unfreeze, upgrade, and cancel operations each take `expected_member_version` as a non-optional input. If the supplied value does not equal the member's current `version`, the request is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412), and no state change occurs.

The upgrade path is the canonical illustration. Upgrading a member to a higher tier requires `expected_member_version` to match the target member's current `version`. Because a successful upgrade legitimately supersedes the prior plan and increments `Member.version`, a client that read the member before some other upgrade landed will carry a stale version; that later request is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412) on the stale-version precondition alone, preventing the client from overwriting a plan change it never observed. This is stated purely as a stale-version precondition over `Member.version`; it does not depend on requests overlapping in time.

### 2.10. The Salon Ledger Invariant

The salon keeps a single financial ledger row, the `SalonLedger`, distinguished by a `singleton_key` whose value must equal `SALON` and is unique across the system, so only one ledger row ever exists. The ledger tracks three running totals, all in cents: `deferred_revenue_cents`, the outstanding freeze credits the salon owes to members; `collected_dues_cents`, the cumulative successfully collected EFT dues; and `collected_retail_cents`, the cumulative net retail revenue. These totals are derived: they move only as the workflows in Section 3 dictate, and they must stay mutually consistent with the member-level `account_credit_cents` and product stock figures they mirror. In particular, the salon's `deferred_revenue_cents` rises by exactly the same amount that a freeze adds to a member's `account_credit_cents`, and falls by exactly that amount when the credit is drawn down or a cancellation reverses it.

## 3. Business Logic & Workflows

### 3.1. Membership Plans and Member Registration

Membership configuration begins with a `SalonManager` defining a `MembershipPlan`. Each plan carries a `tier_code` — one of `BASIC`, `PREMIUM`, or `UNLIMITED`, unique across plans — and a recurring `monthly_fee_cents`, which must be zero or greater. A plan may also set a `retail_discount_pct`, a fractional product discount for members on that plan (for example, 0.10 for ten percent) that must be between 0 and 0.5 inclusive and defaults to 0. The `weekly_uv_session_cap` sets the maximum number of UV sessions in `COMPLETED` or `IN_PROGRESS` status that an adult member on this plan may take within one ISO week; a value of 0 means unlimited and is the default. Finally, `includes_spray` is a boolean, defaulting to true, indicating whether spray-room sessions are covered by the membership at no per-session charge.

A `FrontDeskStaff` operator registers a new `Member` by supplying `full_name`, `date_of_birth` (a date taken at midnight UTC), `skin_type`, and `plan_id`. The `skin_type` is the member's Fitzpatrick classification, one of `I`, `II`, `III`, `IV`, `V`, or `VI`. The `plan_id` is the member's current plan and may be null only when no membership has ever been activated. On registration the member begins with lifecycle `status` of `PENDING`, a `billing_status` of `CURRENT`, an `account_credit_cents` of 0, and a `completed_uv_session_count` of 0. The `cycle_anchor_at` and `frozen_at` timestamps are system-managed and are not set at registration. Several member fields are computed on every read against the logical clock: `is_minor` is true when the member's age — the logical clock's current instant minus `date_of_birth` — is under 18 years; `completed_uv_session_count` is the number of this member's sessions with `kind` of `UV` and `status` of `COMPLETED`; and `account_credit_cents` reflects the prepaid/refund credit balance, increased by freeze proration credit and decreased by retail purchases that draw on it.

### 3.2. Activation and the Recurring Billing Cycle

A newly registered member sits in `PENDING` until first dues clear. The billing simulator records the first dues attempt: a `BillingSystem` actor charges the first dues for a `PENDING` member with a pinned `outcome`, creating a `Payment` of `kind` `EFT_DUES`. When that pinned outcome is `SUCCEEDED`, the salon ledger's `collected_dues_cents` rises by the plan's `monthly_fee_cents`. Activation then transitions the member from `PENDING` to `ACTIVE`, driven by the `BillingSystem`. Activation requires that a `SUCCEEDED` `EFT_DUES` payment already exists for this member's first cycle — absent it, the activation is rejected with `ERR_DUES_NOT_PAID` — and that the member's `plan_id` resolves to an existing plan, failing with `ERR_PLAN_NOT_FOUND` otherwise. On activation the member's `billing_status` is set to `CURRENT` and `cycle_anchor_at` is set to the current logical-clock instant.

Recurring dues run through the EFT simulator, which charges one member with a pinned processor outcome and advances the `billing_status` dimension. A run is permitted only while the member is `ACTIVE`; frozen members are skipped, and an attempt on a non-active member yields `ERR_MEMBER_NOT_ACTIVE`. A normal due-date run also requires that the logical clock has reached or passed `cycle_anchor_at` plus 30 days; if the cycle is not yet due, the run is rejected with `ERR_CYCLE_NOT_DUE`. On a `SUCCEEDED` charge while `CURRENT`, the member stays `CURRENT`: a `Payment` of `kind` `EFT_DUES` with `outcome` `SUCCEEDED` and `amount_cents` equal to the plan's `monthly_fee_cents` is created, `cycle_anchor_at` advances by 30 days, and the ledger's `collected_dues_cents` rises by `monthly_fee_cents`. On a `DECLINED` charge while `CURRENT` and past due, the member moves from `CURRENT` to `PAST_DUE`: a `DECLINED` `EFT_DUES` payment is created and `cycle_anchor_at` is not advanced.

A `PAST_DUE` member who is retried successfully returns from `PAST_DUE` to `CURRENT`: a `SUCCEEDED` `EFT_DUES` payment is created, `cycle_anchor_at` advances by 30 days, and `collected_dues_cents` rises by `monthly_fee_cents`. A retry still requires the member to be `ACTIVE`, failing with `ERR_MEMBER_NOT_ACTIVE` otherwise. If instead the grace window lapses, a `PAST_DUE` member moves from `PAST_DUE` to `SUSPENDED`: this path requires the member to currently be `PAST_DUE` (otherwise `ERR_NOT_PAST_DUE`) and requires the logical clock to have reached or passed `cycle_anchor_at` plus 30 days plus a further 7 days of grace (otherwise `ERR_GRACE_NOT_ELAPSED`). No new payment is created on suspension, and a `SUSPENDED` member becomes ineligible to reserve sessions, enforced as a precondition on session creation.

### 3.3. Freeze, Unfreeze, Upgrade, and Cancellation

A `Member` may freeze its own active membership, moving the lifecycle `status` from `ACTIVE` to `FROZEN`. Freezing requires the member to currently be `ACTIVE` (otherwise `ERR_MEMBER_NOT_ACTIVE`) and requires that the member has no session in `RESERVED` or `IN_PROGRESS` status (otherwise `ERR_OPEN_SESSION_EXISTS`); it also carries the `expected_member_version` OCC check of Section 2.9. On freeze, `frozen_at` is set to the current logical instant, a freeze proration credit (computed in Section 3.8) is added to the member's `account_credit_cents`, the same credit amount is added to the salon ledger's `deferred_revenue_cents`, and `Member.version` is incremented by one.

A `Member` resumes a frozen membership by unfreezing, moving `status` from `FROZEN` back to `ACTIVE`. Unfreeze requires the member to currently be `FROZEN` (otherwise `ERR_MEMBER_NOT_FROZEN`) and carries the same `expected_member_version` OCC check. On unfreeze, `frozen_at` is cleared to null, `cycle_anchor_at` is advanced by the frozen duration — the current logical instant minus the recorded `frozen_at` — so that the remaining days of the cycle are preserved across the freeze, and `Member.version` is incremented by one.

A `Member` may upgrade to a higher-fee plan by supplying `new_plan_id` and `expected_member_version`. The upgrade is OCC-guarded as described in Section 2.9, computes a prorated upgrade charge (Section 3.8), and records a `Payment` of `kind` `UPGRADE`. The next upgrade's processor result is pinned ahead of time by the billing simulator, which sets the upgrade `outcome` for a member (defaulting to `SUCCEEDED` if never set); when the charge result is `SUCCEEDED`, the member's `plan_id` is set to `new_plan_id`. Each upgrade increments `Member.version` by one.

A `Member` cancels its membership, moving `status` to the terminal `CANCELLED` state from `PENDING`, `ACTIVE`, or `FROZEN`. Cancellation requires the member to be in one of those three states (otherwise `ERR_MEMBER_ALREADY_CANCELLED`), requires no session in `RESERVED` or `IN_PROGRESS` status (otherwise `ERR_OPEN_SESSION_EXISTS`), and carries the `expected_member_version` OCC check. If — and only if — the member is `FROZEN` at cancel time, the cancellation runs a compensating reversal of the freeze: the freeze proration credit recorded at freeze is subtracted from the member's `account_credit_cents`, and the same amount is subtracted from the salon ledger's `deferred_revenue_cents`, restoring the deferred-revenue invariant. Cancellation increments `Member.version` by one.

### 3.4. Booking a Session: Walk-In and Reservation

A session is booked by either a `FrontDeskStaff` operator or the `Member` placing its own booking. The request supplies `member_id`, `kind` (`UV` or `SPRAY`), `booking_mode` (`RESERVATION` or `WALK_IN`), `start_at`, and `requested_seconds`, plus exactly one of `equipment_id` (required when `kind` is `UV`, and absent when `kind` is `SPRAY`) or `spray_room_id` (required when `kind` is `SPRAY`, and absent when `kind` is `UV`). A new session is created in `RESERVED` status with `end_at` computed as `start_at` plus `requested_seconds`; for a UV session, `allowed_seconds` is populated from the dose calculation of Section 3.8 and is left null for spray sessions.

The body must be well-formed: required fields present, enums in range, `requested_seconds` at least 1, and the UV-versus-spray consistency just described — a mismatch (a UV booking missing `equipment_id` or carrying a `spray_room_id`, or the spray mirror image) is rejected with `ERR_INVALID_REQUEST`. Once shape is valid, session creation enforces its domain rules in a fixed sequence. First comes member booking eligibility: the booking member must be `ACTIVE` and must not have `billing_status` of `SUSPENDED`; a suspended or non-active member cannot book and is rejected with `ERR_MEMBER_NOT_BOOKABLE`. The remaining checks apply only to UV bookings and run in this order: skin-type prohibition, minor consent, minor frequency, adult frequency, cool-down, dose ceiling, and finally the equipment slot-conflict check; spray bookings instead run the spray-room slot-conflict check. The specific thresholds for the dose, frequency, cool-down, and slot-conflict checks are detailed in Sections 3.5, 3.6, and 3.8.

### 3.5. UV Safety: Skin Type, Minor Consent, and Frequency

Fitzpatrick skin type `I` is categorically prohibited from UV exposure, because that skin type always burns; any UV booking for a member whose `skin_type` is `I` is rejected with `ERR_SKIN_TYPE_UV_PROHIBITED`. This is checked before any dose math runs.

Minor members face two additional UV gates, both regulatory. First, a minor member must have a valid, unexpired guardian consent on file to reserve a UV session: there must exist a `ConsentRecord` for the member whose `expires_at` is strictly after the current logical instant. A `ConsentRecord` is created by a `FrontDeskStaff` operator under the minor member, capturing the `member_id` it authorizes, the `guardian_name` of the consenting parent or guardian, and the consent's `expires_at` validity-end instant. If no such unexpired consent exists for a minor's UV booking, the booking is rejected with `ERR_MINOR_CONSENT_REQUIRED`. Second, a minor may take at most one UV session per ISO week; this minor cap is regulatory and overrides whatever the plan's `weekly_uv_session_cap` would permit. If a minor already has at least one UV session counted for the target ISO week, a further UV booking is rejected with `ERR_MINOR_FREQUENCY_EXCEEDED`.

Adult members are instead bound by their plan's weekly cap. When the plan's `weekly_uv_session_cap` is non-zero and the count of the member's UV sessions in the target ISO week has already reached that cap, the booking is rejected with `ERR_FREQUENCY_CAP_EXCEEDED`; a cap of zero means unlimited and is never exceeded. For both the minor and adult frequency checks, the weekly count includes only this member's UV sessions whose `start_at` falls within the target ISO week and whose status is `RESERVED`, `IN_PROGRESS`, or `COMPLETED`; sessions in `NO_SHOW` or `CANCELLED` status are excluded from the count. An ISO week here runs from Monday at 00:00:00 UTC up to but not including the following Monday at 00:00:00 UTC, as a half-open interval containing the session's `start_at`.

### 3.6. UV Cool-Down and Equipment/Room Slot Conflicts

Beyond frequency, consecutive UV sessions must be spaced apart. A UV booking is rejected with `ERR_UV_COOLDOWN_NOT_ELAPSED` if the member's most recent prior UV session began less than 24 hours before the new booking's `start_at`. "Most recent prior UV session" is the latest session for this member with `kind` `UV` whose status is `IN_PROGRESS` or `COMPLETED`, selected by the greatest `start_at` and, on a tie, by the earliest `created_at`. If no such prior session exists, the cool-down gate passes. The required spacing is 24 hours, measured between the two sessions' `start_at` instants; a gap of less than 24 hours fails, and a gap of exactly 24 hours or more passes.

UV bookings must also not collide on the physical unit. The requested half-open interval `[start_at, end_at)`, extended by the equipment's `turnaround_seconds` buffer appended after `end_at`, must not overlap any existing `RESERVED` or `IN_PROGRESS` session on the same equipment. The `turnaround_seconds` value is a mandatory cool-down and cleaning buffer applied after a session's end before the unit may be booked again, and it defaults to 600 seconds (ten minutes). Because intervals are half-open, a new booking whose `start_at` is exactly at the boundary where a prior session's buffer ends is allowed; a true overlap is rejected with `ERR_EQUIPMENT_SLOT_CONFLICT`. Spray bookings undergo the analogous check against the spray room's `ventilation_buffer_seconds`, the buffer applied after a spray session's end before the room is bookable again, defaulting to 300 seconds (five minutes): the requested interval plus that ventilation buffer must not overlap any `RESERVED` or `IN_PROGRESS` session on the same room, with adjacency at the exact buffer boundary allowed and a real overlap rejected with `ERR_ROOM_SLOT_CONFLICT`.

### 3.7. Running the Session: Start, Complete, Cancel, No-Show

A `FrontDeskStaff` operator starts a reserved session, advancing it from `RESERVED` to `IN_PROGRESS`. Starting requires the session to currently be `RESERVED` (otherwise `ERR_SESSION_NOT_RESERVED`); for a UV session the booked equipment must be `AVAILABLE` (otherwise `ERR_EQUIPMENT_UNAVAILABLE`), and for a spray session the booked room must be `AVAILABLE` (otherwise `ERR_ROOM_UNAVAILABLE`). On start, a UV session sets the equipment's status to `IN_USE`, and a spray session sets the room's status to `IN_USE`. The dose ceiling is re-evaluated at start as described in Section 3.8.

A `FrontDeskStaff` operator then completes an in-progress session, advancing it from `IN_PROGRESS` to `COMPLETED`; this requires the session to currently be `IN_PROGRESS` (otherwise `ERR_SESSION_NOT_IN_PROGRESS`). Completion of a UV session is a cascade: the equipment returns to `AVAILABLE`, the equipment's `sessions_since_service` increases by one, and the member's `completed_uv_session_count` increases by one. If, after that increment, the equipment's `sessions_since_service` reaches the service threshold, the equipment is instead driven to `MAINTENANCE` — this maintenance set overrides the `AVAILABLE` set that would otherwise apply, so the unit ends in `MAINTENANCE`, not `AVAILABLE`. Completion of a spray session simply returns the room to `AVAILABLE`; spray completion does not touch any equipment counter or the member's UV count.

A reserved session may also be abandoned in two ways. Either a `FrontDeskStaff` operator or the booking `Member` may cancel a reserved session, moving it from `RESERVED` to the terminal `CANCELLED` state; this requires the session to be `RESERVED` (otherwise `ERR_SESSION_NOT_RESERVED`) and frees the reserved interval on the unit so a new `RESERVED` session may reuse the same slot. Separately, a `FrontDeskStaff` operator marks a reserved past-due session as a no-show, moving it from `RESERVED` to the terminal `NO_SHOW` state; this requires the session to be `RESERVED` (otherwise `ERR_SESSION_NOT_RESERVED`) and requires that the logical clock has reached or passed the session's `start_at` (otherwise `ERR_TOO_EARLY_FOR_NO_SHOW`). A no-show frees the reserved interval but, unlike completion, does not increment the member's `completed_uv_session_count`.

### 3.8. Dose, Proration, and Service-Threshold Calculations

**UV dose allowance.** At UV reservation the permitted exposure is computed and copied into the session's `allowed_seconds`. If the member's `skin_type` is `I` the booking is rejected outright (Section 3.5). Otherwise a base exposure and a per-type cap are read from fixed tables keyed by skin type. The base seconds are 90 for type `II`, 120 for type `III`, 180 for type `IV`, 240 for type `V`, and 300 for type `VI`. The cap seconds are 240 for type `II`, 480 for type `III`, 600 for type `IV`, 720 for type `V`, and 900 for type `VI`. The escalated allowance is the base plus 30 seconds for each of the member's completed UV sessions — that is, the base plus the member's `completed_uv_session_count` multiplied by 30. The session's `allowed_seconds` is then the minimum of three quantities: the escalated allowance, the per-type cap, and the booked equipment's `max_exposure_seconds`. A UV booking passes the dose gate when its `requested_seconds` is less than or equal to `allowed_seconds`; a request of exactly `allowed_seconds` passes, and a request of `allowed_seconds` plus one is rejected with `ERR_DOSE_EXCEEDS_LIMIT`. The allowance is whole seconds with no rounding. Only `COMPLETED` UV sessions count toward `completed_uv_session_count`.

This dose check is evaluated twice with the same formula but different inputs. At reservation it is a forward-looking estimate using `completed_uv_session_count` as observed at reservation time. It is re-evaluated when the session is started, using `completed_uv_session_count` as of the start instant; because intervening UV sessions may have completed in the meantime, the actual escalated allowance at start is greater than or equal to the reservation-time estimate, so a `requested_seconds` that was borderline-valid at reservation remains valid at start.

**Equipment max exposure.** Each `Equipment` unit is created by a `SalonManager` with a `name`, a `kind` (`BED` or `BOOTH`), a `max_exposure_seconds` ceiling of at least 1, and an optional `turnaround_seconds` (default 600). A new unit starts `AVAILABLE` with `sessions_since_service` at 0, where `sessions_since_service` counts completed sessions since the last maintenance reset.

**Service threshold.** On each UV session completion, the equipment's `sessions_since_service` is incremented by one (only completed UV sessions count). The service threshold is 2: when `sessions_since_service` reaches 2 or more after the completing session — that is, on the second completed UV session since the last service — the equipment is driven to `MAINTENANCE` and becomes unbookable until serviced; otherwise it returns to `AVAILABLE`. A `SalonManager` services a unit that is in `MAINTENANCE`, moving it from `MAINTENANCE` back to `AVAILABLE`; servicing requires the unit to currently be `MAINTENANCE` (otherwise `ERR_EQUIPMENT_NOT_IN_MAINTENANCE`), supplies a `reason` (`SCHEDULED_THRESHOLD` or `MANUAL`), creates a `MaintenanceLog` capturing the serviced `equipment_id`, the `reason`, and the `sessions_at_service` value of `sessions_since_service` taken before reset, and then resets `sessions_since_service` to 0. A `SalonManager` may also retire a unit, moving it to the terminal `RETIRED` state from either `AVAILABLE` or `MAINTENANCE`; retiring is blocked while the unit is `IN_USE`, in which case it is rejected with `ERR_EQUIPMENT_IN_USE`, and a retired unit is permanently unbookable.

**Freeze proration credit.** When an active member freezes, the credit returned is computed from the daily rate and the unused days of the current cycle. The daily rate in cents is the plan's `monthly_fee_cents` divided by 30, rounded half up to whole cents. The elapsed whole days are the floor of the current logical instant minus `cycle_anchor_at`, expressed in days (dividing the elapsed seconds by 86,400 and taking the floor), then clamped to lie between 0 and 30. The unused days are 30 minus the clamped elapsed days. The freeze proration credit is the daily rate multiplied by the unused days, an exact integer number of cents, and this exact amount is what is added both to the member's `account_credit_cents` and to the salon ledger's `deferred_revenue_cents`.

**Upgrade proration charge.** An upgrade is permitted only when the new plan's `monthly_fee_cents` is strictly greater than the current plan's `monthly_fee_cents`; a lateral or lower fee is rejected with `ERR_NOT_AN_UPGRADE`. The old daily rate is the current plan's `monthly_fee_cents` divided by 30, rounded half up to whole cents, and the new daily rate is the new plan's `monthly_fee_cents` divided by 30, rounded half up to whole cents. The elapsed whole days are computed exactly as for the freeze — the floor of the elapsed seconds divided by 86,400, clamped between 0 and 30 — and the remaining days are 30 minus those elapsed days. The upgrade charge in cents is the difference of the two daily rates (new daily minus old daily) multiplied by the remaining days, an exact integer of cents, billed as the `UPGRADE` payment.

**Retail order total.** A retail order is priced by discounting and rounding each line independently and then summing — the per-line-then-sum order is pinned, and sum-then-round is explicitly not used. The discount is the purchasing member's plan `retail_discount_pct`, or 0 when the member has no active plan discount. Processing the order's `lines` in the exact order they appear in the request array, each line's total is the product's `unit_price_cents` multiplied by the line's `quantity` multiplied by one minus the discount, rounded half up to whole cents. The order's `subtotal_cents` is the sum of those already-rounded line totals. The `credit_applied_cents` is the smaller of the member's `account_credit_cents` and the `subtotal_cents`. The `charged_cents` is the `subtotal_cents` minus `credit_applied_cents`. Because each line is rounded before summing, the result can differ by up to a cent from a sum-then-round approach; the per-line order is authoritative.

### 3.9. Retail Products, Orders, and Refunds

A `SalonManager` stocks the retail line by creating a `Product` with a `sku` (unique across products), a `name`, a `unit_price_cents` of at least 0, and an `initial_stock` of at least 0. A new product's `stock_on_hand` begins equal to `initial_stock` and its `units_sold` begins at 0. The salon maintains the invariant that `stock_on_hand` plus `units_sold` always equals `initial_stock`: every sale decrements `stock_on_hand` and increments `units_sold`, and every refund restores them in mirror.

A retail order is placed by a `FrontDeskStaff` operator or by the purchasing `Member`, supplying `member_id` and `lines` — an array whose entries each carry a `product_id` referencing a product and a `quantity` of at least 1. The order is created in `PAID` status with `subtotal_cents`, `credit_applied_cents`, and `charged_cents` computed per Section 3.8. As a side effect of a paid order, each referenced product's `stock_on_hand` is reduced by the line `quantity` and its `units_sold` increased by the same `quantity`; the member's `account_credit_cents` is reduced by the order's `credit_applied_cents`; the salon ledger's `collected_retail_cents` rises by the order's `charged_cents`; and any credit drawn lowers the salon's deferred obligation accordingly.

A `FrontDeskStaff` operator may refund a paid order, moving it from `PAID` to the terminal `REFUNDED` state; refunding requires the order to currently be `PAID`, otherwise it is rejected with `ERR_ORDER_ALREADY_REFUNDED`. A refund is a full compensating reversal: for each line, the product's `stock_on_hand` is increased by the line `quantity` and its `units_sold` decreased by the same `quantity`, restoring the stock invariant; the member's `account_credit_cents` is increased by the order's `credit_applied_cents`, returning the credit that had been drawn; the salon ledger's `collected_retail_cents` is decreased by the order's `charged_cents`; and the salon ledger's `deferred_revenue_cents` is increased by the order's `credit_applied_cents`, re-deferring the returned credit.

### 3.10. Payments, Spray Rooms, and the Ledger Audit Trail

Every charge attempt is recorded as a `Payment` carrying the charged `member_id`, a `kind` of `EFT_DUES`, `RETAIL`, or `UPGRADE`, an `amount_cents` of at least 0, an `outcome` of `SUCCEEDED` or `DECLINED` fed by the billing simulator, and a `retail_order_id` that is set only when the `kind` is `RETAIL` and is null otherwise. Payments are immutable records and can be listed or fetched for audit, filtered by `member_id` and by `retail_order_id`, which provides reverse reachability from a member or a retail order to its charges.

Spray rooms are configured by a `SalonManager`, who creates a `SprayRoom` with a `name` and an optional `ventilation_buffer_seconds` (default 300); a new room starts `AVAILABLE`. The salon's single ledger row is readable by a `SalonManager` and reports the live `deferred_revenue_cents`, `collected_dues_cents`, and `collected_retail_cents` totals described in Section 2.10, all kept consistent with the per-member credits and per-product stock figures they summarize.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new record to a collection return `201 Created`. Operations that modify an existing resource — including all state transitions and the test-driving and billing-simulator capabilities — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/membership-plans` | Create a membership plan | SalonManager |
| GET | `/membership-plans` | List membership plans | SalonManager, FrontDeskStaff, Member |
| GET | `/membership-plans/{planId}` | Get a membership plan | SalonManager, FrontDeskStaff, Member |
| POST | `/members` | Register a member | FrontDeskStaff |
| GET | `/members` | List members (filterable by plan_id) | SalonManager, FrontDeskStaff |
| GET | `/members/{memberId}` | Get a member | SalonManager, FrontDeskStaff, Member |
| POST | `/members/{memberId}/activate` | Activate a PENDING member after first dues | BillingSystem |
| POST | `/members/{memberId}/freeze` | Freeze an active membership | Member |
| POST | `/members/{memberId}/unfreeze` | Resume a frozen membership | Member |
| POST | `/members/{memberId}/upgrade` | Upgrade to a higher-fee plan (OCC-guarded) | Member |
| POST | `/members/{memberId}/cancel` | Cancel a membership | Member |
| POST | `/members/{id}/consents` | Record guardian consent for a minor | FrontDeskStaff |
| GET | `/members/{id}/consents` | List consent records for a member | SalonManager, FrontDeskStaff, Member |
| POST | `/equipment` | Create a UV bed/booth unit | SalonManager |
| GET | `/equipment` | List equipment units | SalonManager, FrontDeskStaff, Member |
| GET | `/equipment/{equipmentId}` | Get an equipment unit | SalonManager, FrontDeskStaff, Member |
| POST | `/equipment/{equipmentId}/service` | Service a maintenance unit and reset its counter | SalonManager |
| POST | `/equipment/{equipmentId}/retire` | Permanently retire a unit | SalonManager |
| GET | `/equipment/{id}/maintenance-logs` | List maintenance logs for a unit | SalonManager, FrontDeskStaff |
| POST | `/spray-rooms` | Create a spray-tan room | SalonManager |
| GET | `/spray-rooms` | List spray rooms | SalonManager, FrontDeskStaff, Member |
| GET | `/spray-rooms/{roomId}` | Get a spray room | SalonManager, FrontDeskStaff, Member |
| POST | `/sessions` | Create a session (reservation or walk-in) | FrontDeskStaff, Member |
| GET | `/sessions` | List sessions (filterable by member_id, equipment_id, spray_room_id) | SalonManager, FrontDeskStaff, Member |
| GET | `/sessions/{sessionId}` | Get a session | SalonManager, FrontDeskStaff, Member |
| POST | `/sessions/{sessionId}/start` | Begin a reserved session | FrontDeskStaff |
| POST | `/sessions/{sessionId}/complete` | Complete an in-progress session | FrontDeskStaff |
| POST | `/sessions/{sessionId}/cancel` | Cancel a reserved session | FrontDeskStaff, Member |
| POST | `/sessions/{sessionId}/no-show` | Mark a reserved past-due session as no-show | FrontDeskStaff |
| POST | `/products` | Create a retail product | SalonManager |
| GET | `/products` | List products | SalonManager, FrontDeskStaff, Member |
| GET | `/products/{productId}` | Get a product | SalonManager, FrontDeskStaff, Member |
| POST | `/retail-orders` | Create a paid retail order | FrontDeskStaff, Member |
| GET | `/retail-orders` | List retail orders (filterable by member_id) | SalonManager, FrontDeskStaff, Member |
| GET | `/retail-orders/{orderId}` | Get a retail order | SalonManager, FrontDeskStaff, Member |
| POST | `/retail-orders/{orderId}/refund` | Refund a paid order | FrontDeskStaff |
| GET | `/payments` | List payments (filterable by member_id, retail_order_id) | SalonManager, FrontDeskStaff, BillingSystem |
| GET | `/payments/{paymentId}` | Get a single payment | SalonManager, FrontDeskStaff, BillingSystem |
| GET | `/salon-ledger` | Get the singleton salon ledger | SalonManager |
| POST | `/_clock/set_current_utc` | Set the logical clock | SalonManager, BillingSystem |
| POST | `/_billing/charge-first-dues` | Record the first EFT_DUES payment with a pinned outcome | BillingSystem |
| POST | `/_billing/run-eft` | Run the recurring EFT charge with a pinned outcome | BillingSystem |
| POST | `/_billing/set-upgrade-outcome` | Pin the next upgrade's processor outcome | BillingSystem |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_MEMBER_NOT_FROZEN` | 409 |
| `ERR_MEMBER_ALREADY_CANCELLED` | 409 |
| `ERR_DUES_NOT_PAID` | 409 |
| `ERR_OPEN_SESSION_EXISTS` | 409 |
| `ERR_SESSION_NOT_RESERVED` | 409 |
| `ERR_SESSION_NOT_IN_PROGRESS` | 409 |
| `ERR_TOO_EARLY_FOR_NO_SHOW` | 409 |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 |
| `ERR_ROOM_UNAVAILABLE` | 409 |
| `ERR_EQUIPMENT_NOT_IN_MAINTENANCE` | 409 |
| `ERR_EQUIPMENT_IN_USE` | 409 |
| `ERR_ORDER_ALREADY_REFUNDED` | 409 |
| `ERR_CYCLE_NOT_DUE` | 409 |
| `ERR_NOT_PAST_DUE` | 409 |
| `ERR_GRACE_NOT_ELAPSED` | 409 |
| `ERR_NOT_AN_UPGRADE` | 409 |
| `ERR_MEMBER_NOT_BOOKABLE` | 409 |
| `ERR_SKIN_TYPE_UV_PROHIBITED` | 403 |
| `ERR_MINOR_CONSENT_REQUIRED` | 403 |
| `ERR_MINOR_FREQUENCY_EXCEEDED` | 403 |
| `ERR_FREQUENCY_CAP_EXCEEDED` | 409 |
| `ERR_UV_COOLDOWN_NOT_ELAPSED` | 409 |
| `ERR_DOSE_EXCEEDS_LIMIT` | 422 |
| `ERR_EQUIPMENT_SLOT_CONFLICT` | 409 |
| `ERR_ROOM_SLOT_CONFLICT` | 409 |
| `ERR_STALE_MEMBER_VERSION` | 412 |
