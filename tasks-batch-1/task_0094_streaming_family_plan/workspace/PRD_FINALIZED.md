# Streaming Family Plan API — Product Requirements Document

## 1. Introduction

The Streaming Family Plan API powers the back-office of a subscription video service built around the household rather than the individual viewer. A single paying household — modeled as an **Account** owned by one **AccountOwner** — sits on a chosen subscription tier and fans out into a small constellation of viewer **Profiles**, registered playback **Devices**, in-flight **StreamSessions**, offline **Downloads**, and cross-device resume markers. Each plan tier sells a bundle of quotas: how many profiles a family may carve out, how many screens may stream at once, how many devices may be registered, how many titles each profile may stash offline, and whether playback is ad-free or ad-supported. The product's central tension is that these quotas are finite and shared, so almost every write in the system is really a question of whether one more profile, screen, device, or download still fits inside the envelope the household has paid for.

Layered on top of the quota machinery is a parental-controls regime. A guardian can wrap any profile in a control envelope that caps the maturity rating a profile may reach, fences off a nightly curfew window, and meters a daily watch-minute allowance. The system must reconcile these per-profile guardrails against a global content catalog of **Titles** carrying their own maturity ratings and runtimes, and it must do so while a logical clock — advanced only through an administrative test seam — drives invite expiry, offline-license expiry, and the midnight rollover of daily usage. Finally, because billing is folded directly onto the Account, mid-period plan changes must reprorate the open billing period, and the invoice and plan-change paths are guarded against acting on a stale view of the Account. This document specifies the full contract: the resource model, the lifecycles, the quota and parental gates, the proration arithmetic, and the access-control rules that bind each actor to the slice of the system it is allowed to touch.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts. The system recognizes exactly four roles: `PlatformAdmin`, `AccountOwner`, `ProfileUser`, and `Anonymous`. When either header is missing or malformed on an endpoint that requires authentication, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`. When an entity-backed role is well-formed and permitted but does not own the resource it targets, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The four roles bind to identity in two different ways. When `X-User-Role` is `AccountOwner`, `X-User-ID` is the `id` of the acting `Account`; any ownership check on a resource that ultimately rolls up to an Account compares that resource's owning account against `X-User-ID` (directly for resources carrying an `account_id`, and transitively for resources that reference a `Profile`, since a profile's `account_id` names its account). When `X-User-Role` is `ProfileUser`, `X-User-ID` is the `id` of the acting `Profile`; ownership checks on streams, downloads, and watch-progress compare the `profile_id` referenced by the request to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — it governs the shared catalog and the clock seam, and the server does not compare it to any entity's `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque, non-persisted identifier; an anonymous caller is a token-bearing invitee whose authority comes entirely from presenting the correct invite `token`, and the two invite-response endpoints — accepting and declining an invite — are the only operations that do not require authentication headers at all.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single page returns; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter names how many leading items to skip and defaults to 0.

Unless an endpoint explicitly states otherwise, every list is returned sorted by the resources' creation timestamp in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full unpaged result set and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties and Identifier Hygiene

Most resources in the system carry a uniform spine of system-managed fields. Each is assigned an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp in the same format that is refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one on each modification. These full-spine resources are the **Account**, **Profile**, **ParentalControl**, **Invite**, **Device**, **StreamSession**, **Download**, and **WatchProgress**.

Three resources are deliberately leaner. A **SubscriptionPlan**, a **Title**, and a **PlanChange** carry only an `id` (a server-minted UUID) and a `created_at` timestamp; they have neither an `updated_at` field nor a `version` field, because they are write-once configuration or immutable audit records rather than living, mutable aggregates. For a PlanChange, `created_at` doubles as the change's effective instant within the billing period.

When a request names several resources — for example a path identifier plus body references — existence is validated left to right, and the first identifier that fails to resolve to a stored entity yields `ERR_NOT_FOUND` before any later identifier is examined.

### 2.5. Quota Envelopes and Denormalized Counters

The whole system revolves around the quota bundle sold by the Account's current plan. The plan fixes the ceiling on non-`ARCHIVED` profiles via `max_profiles`, the number of screens that may stream at once via `concurrent_stream_cap`, the number of `REGISTERED` devices via `max_registered_devices`, and the count of live offline copies a single profile may hold via `download_quota_per_profile`. To answer cap questions without scanning, the Account maintains two denormalized counters: `active_stream_count`, the number of its StreamSessions presently in `ACTIVE` state, and `registered_device_count`, the number of its Devices presently in `REGISTERED` state. Both default to 0 at account creation. Every transition that opens or closes a stream, and every transition that registers or deregisters a device, must keep its counter exactly synchronized with reality; these reconciliations are mutations of the Account and therefore refresh `updated_at` and increment `version` along with the explicit account-state transitions described in §3.

### 2.6. Billing, the Wallet, and Proration Precision

Billing is folded directly onto the Account. The Account holds a prepaid `wallet_credit_cents` balance that is debited and credited by invoicing, reactivation, and invite seat-holds, an integer day-of-month `billing_anchor_day` in the range 1 through 28 on which each billing period opens, and a `billing_status` that is either `OPEN` while the current period is still accruing or `INVOICED` once it has been settled. Two computed money fields track the period's accrual: `period_charge_cents`, the plan fee accrued for the current period after accounting for any mid-period plan changes, and `proration_adjustment_cents`, a signed figure describing how that accrual compares to one flat period of the plan now in force.

The proration arithmetic — named here the **cycle charge** computation — treats a billing period as spanning 30 whole days counted from period day 0. It is evaluated chronologically, never forward-projected. To compute it, walk the period's plan changes in ascending `created_at` order, breaking ties by `created_at` and then by the PlanChange `id` only to stabilize equal-millisecond timestamps. The Account's plan at period open furnishes the first segment; each plan change opens a new segment beginning on its effective day, and a given day belongs to whichever segment's plan is in force at that day's 00:00:00Z, treating each day's boundaries as half-open. For any plan, the exact daily rate is its `monthly_fee_cents` divided by 30, kept as an exact real number and never rounded per day. Each segment contributes its daily rate multiplied by the number of days in that segment. The `period_charge_cents` is the sum of all segment contributions, rounded once at the very end using round-half-up to whole integer cents — the daily contributions are summed exactly first and rounded only at the end, never per day and never per segment. The `proration_adjustment_cents` is then that rounded `period_charge_cents` minus the current plan's `monthly_fee_cents`: positive when mid-period upgrades pushed the prorated total above one flat period of the final plan, negative on a net downgrade. The net charge actually settled at invoice equals `period_charge_cents`; the adjustment is purely descriptive and is already folded into that figure. When no plan change landed in the period, there is exactly one segment spanning all 30 days, `period_charge_cents` equals the plan's `monthly_fee_cents`, and `proration_adjustment_cents` is 0.

All money fields are integer cents; the only rounding the system performs is the single round-half-up at the end of the cycle-charge sum. Counts such as ad breaks, watch minutes, and download sizes are likewise whole integers with no fractional accumulation.

### 2.7. Optimistic Concurrency on the Account

Two Account-level writes are guarded against acting on a stale view of the Account: applying a plan change, and invoicing the open period. Both require an `expected_account_version` field in the request body carrying the client's last observed `version` of the target Account. A plan-change request must carry `expected_account_version` equal to the Account's current `version`; if another writer has advanced the Account's version since the client last read it — for instance by having already applied a plan change that rewrote `period_charge_cents` — the request is rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412, so the new change cannot silently stack on a superseded plan binding. An invoice request likewise must carry `expected_account_version` equal to the Account's current `version`; if the Account has been mutated since the client read it — a plan change that altered the proration basis, or a reactivation that consumed credit — the stale-version invoice is refused with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412 rather than settling against an out-of-date charge basis. No other endpoint takes a version field; the account suspend, reactivate, and close transitions also accept `expected_account_version` and reject a mismatch under the same stale-version rule, but only plan-change and invoice are the OCC-guarded writes that a stale version protects in the proration/billing sense above.

### 2.8. The Parental-Control Envelope and the Rating Scale

Maturity ratings form a strict ordered scale from least to most restrictive: `G`, then `PG`, then `PG13`, then `R`, then `NC17`. Every profile carries a computed `max_rating_allowed` — the highest rating it may ever stream — derived from its `kind` and then tightened, never loosened, by any parental control. The rating ceiling computation establishes a per-kind default: a `KID` profile defaults to `G`, a `TEEN` profile to `PG13`, and an `ADULT` profile to `NC17`. When a ParentalControl row exists for the profile, `max_rating_allowed` becomes the stricter (the lower on the ordered scale) of that kind default and the control's `max_rating`; with no control row, it is simply the kind default. Because the stricter of the two always wins, a permissive control can never raise a profile above its kind default — a `max_rating` of `R` set on a `KID` profile still leaves the ceiling at `G`. This ceiling is recomputed whenever a profile is created, whenever a parental control is set or replaced, and whenever the profile's ceiling is read.

### 2.9. The Logical Clock and Scheduled Sweeps

Time in this system is a logical clock advanced only through an administrative test seam, never through wall-clock drift. A `PlatformAdmin` advances the clock by supplying a target instant `to_iso8601` and an optional `run_sweeps` flag; setting `run_sweeps` to true fires a set of scheduled sweeps after the clock moves. When sweeps run, three things happen in one pass: every `PENDING` Invite whose `expires_at` the clock has now reached or passed transitions to `EXPIRED` and releases its seat hold; every `READY` Download whose `license_expires_at` the clock has now reached or passed transitions to `EXPIRED` and frees one of its profile's download slots; and every profile that crossed UTC midnight has its `daily_watch_minutes_used` reset to 0. Many of the system's temporal gates — curfews, daily limits, invite validity, and license validity — read their truth from this clock rather than from real time.

## 3. Business Logic & Workflows

### 3.1. Catalog and Plan Configuration

Before any household exists, a `PlatformAdmin` seeds the shared catalog. A subscription tier is created by supplying its `tier` — one of `AD_SUPPORTED`, `AD_FREE`, or `PREMIUM` — together with its `monthly_fee_cents` (a non-negative integer), its quota knobs `max_profiles` (at least 1), `concurrent_stream_cap` (at least 1), `max_registered_devices` (at least 1), and `download_quota_per_profile` (zero or more), and two playback flags. The `ad_free` flag is true on plans whose playback never serves ads — the `AD_FREE` and `PREMIUM` tiers — and false on `AD_SUPPORTED`. The `hd_offline_allowed` flag is true only when downloads may be requested at HD quality, a privilege reserved for the `PREMIUM` tier. Catalog titles are likewise admin-authored: a title is created with a display `name`, a `maturity_rating` drawn from the ordered scale `G`/`PG`/`PG13`/`R`/`NC17`, a whole-minute `runtime_minutes` of at least 1, a `downloadable` flag that defaults to true when omitted, and a `license_size_mb` of at least 1 describing the storage footprint of one SD offline copy in whole megabytes. Both plans and titles are immutable configuration once written, so a reader can list every Account currently bound to a given plan, and can list every plan change that moved some Account onto a given plan, by walking the plan's reverse collections.

### 3.2. Opening and Operating an Account

A household comes into being when an `AccountOwner` creates an Account against a chosen plan. The creation payload names the `plan_id` to bind to, the `owner_email` (which must be unique among all accounts that are not `CLOSED`), the `billing_anchor_day`, and an optional `initial_credit_cents` that seeds the wallet. On creation the Account starts in `ACTIVE` status with `billing_status` set to `OPEN`, its `wallet_credit_cents` seeded to the supplied `initial_credit_cents` (or 0 when omitted), and `period_charge_cents` seeded to the plan's full-period fee. The owner can later read the account back to inspect its denormalized counters and billing fields.

An owner may suspend an active account. Suspension is permitted only while the account is `ACTIVE` and only when the supplied `expected_account_version` matches the account's current `version`; it drives the account from `ACTIVE` to `SUSPENDED`. Suspension halts live playback by force-ending every `ACTIVE` StreamSession on the account — each forced end folds that session's `minutes_watched` into its profile's `daily_watch_minutes_used` exactly as a normal stop would — then resets `active_stream_count` to 0 and increments the account's `version` by one. Profiles, devices, and downloads survive a suspension untouched. Reactivation is the revert leg of this loop: it is permitted only while the account is `SUSPENDED`, only when `expected_account_version` matches the current `version`, and only when `wallet_credit_cents` is at least one period of the current plan's `monthly_fee_cents` — reactivation requires one full period of credit on hand, and falling short is rejected with `ERR_INSUFFICIENT_CREDIT`. A successful reactivation debits `wallet_credit_cents` by the current plan's `monthly_fee_cents`, drives the account back from `SUSPENDED` to `ACTIVE`, and increments `version` by one.

Closing an account is terminal and may be requested from either `ACTIVE` or `SUSPENDED`, in each case requiring a matching `expected_account_version`. Whichever the starting state, the close cascade revokes every `PENDING` Invite on the account and releases each revoked invite's seat hold back to `wallet_credit_cents`, deletes every `DOWNLOADING` or `READY` Download owned by any of the account's profiles, and — if `billing_status` is still `OPEN` — invoices the current period through the cycle-charge computation, finalizing `period_charge_cents` and debiting the wallet by the net charge. When closing from `ACTIVE`, the cascade additionally force-ends every `ACTIVE` StreamSession (folding minutes and driving `active_stream_count` to 0) before the rest; from `SUSPENDED` there are no live streams left to end. Either way the account's `version` is incremented by one as it moves to `CLOSED`. A request to drive an account through a transition its current state does not define — closing an already-closed account, reactivating an active one — is rejected with `ERR_INVALID_STATE`.

Invoicing the open period on its own is a separate owner action, guarded by the optimistic-concurrency rule of §2.7. It runs the cycle-charge computation to finalize `period_charge_cents` and the signed `proration_adjustment_cents`, debits `wallet_credit_cents` by the resulting net charge, flips `billing_status` from `OPEN` to `INVOICED`, and increments `version` by one.

### 3.3. Changing Plans Mid-Period

When an owner moves the household onto a different tier, the request supplies the `to_plan_id` of the destination plan and an `expected_account_version`. Because a plan change supersedes the account's current plan binding and recomputes the open period's proration, it is guarded by optimistic concurrency: if `expected_account_version` does not equal the account's current `version`, the change is rejected with `ERR_STALE_ACCOUNT_VERSION` and the client must re-read before retrying. A successful change snapshots the plan in force beforehand into the new record's `from_plan_id`, repoints `Account.plan_id` to `to_plan_id`, and classifies the change's `direction` by comparing the two plans' `monthly_fee_cents`: `UPGRADE` when the destination costs more, `DOWNGRADE` when it costs less, and `LATERAL` when the fees are equal. The change then re-runs the cycle-charge computation so that `period_charge_cents` and `proration_adjustment_cents` reflect the new segmentation, and increments the account's `version` by one. Each plan change is recorded against its `account_id` with a `created_at` that marks its effective instant, and these records can be listed for an account in ascending creation order.

### 3.4. Profiles and Their Parental Envelopes

An owner carves out viewer profiles on an active account, naming each profile's owning `account_id`, a `display_name`, and a `kind` of `ADULT`, `TEEN`, or `KID`. A profile may be created only while the account is `ACTIVE`, only while the count of non-`ARCHIVED` profiles remains below the plan's `max_profiles` (otherwise `ERR_PROFILE_CAP_REACHED`), and only when the `display_name` is unique among the account's non-`ARCHIVED` profiles (otherwise `ERR_DUPLICATE`). A new profile starts in `ACTIVE` status, and its `max_rating_allowed` is computed straight from its `kind` since no control yet exists. Each profile also exposes a computed `daily_watch_minutes_used` that begins at 0 and tracks minutes consumed within the current clock-day.

Archiving a profile drives it from `ACTIVE` to `ARCHIVED` and is permitted only while it is `ACTIVE` and only when no `ACTIVE` StreamSession references it; archiving cascades a deletion of every `DOWNLOADING` or `READY` Download owned by that profile.

An owner equips a profile with a parental-control envelope by setting or replacing its control row, supplying an explicit `max_rating` from the ordered scale, a `daily_watch_limit_minutes` (zero meaning unlimited), and a nightly curfew defined by `curfew_start_min` and `curfew_end_min`, each expressed as minutes-after-UTC-midnight in the range 0 through 1439. The curfew window opens at `curfew_start_min` inclusive and closes at `curfew_end_min` exclusive; when the end is earlier than the start the window wraps across midnight. At most one control row may exist per profile — a second creation against a profile that already has one is rejected with `ERR_DUPLICATE` — so the operation is a set-or-replace whose `profile_id` names the governed profile. Setting or replacing the control recomputes the profile's `max_rating_allowed` as the stricter of the kind default and the control's `max_rating`, per §2.8. A profile's control envelope can be read back; that read returns an array of length zero or one depending on whether a control has been set.

### 3.5. Devices

An owner registers playback devices on the account, supplying the owning `account_id`, a human `device_label`, a `platform` of `TV`, `MOBILE`, `WEB`, or `TABLET`, and an optional `supports_hd` flag that defaults to true. Registration is permitted only while the account is `ACTIVE` and only while `registered_device_count` remains below the plan's `max_registered_devices`; exceeding the ceiling is rejected with `ERR_DEVICE_CAP_REACHED`. A registered device starts in `REGISTERED` status, and the registration increments `registered_device_count` by one.

Deregistering a device drives it from `REGISTERED` to `DEREGISTERED` and is permitted only while it is `REGISTERED` and only when no `ACTIVE` StreamSession references it. A successful deregistration decrements `registered_device_count` by one and cascades a deletion of every `DOWNLOADING` or `READY` Download licensed to that device, each deletion freeing one slot of the owning profile's download quota.

### 3.6. Streaming: the Gauntlet of Gates

A `ProfileUser` starts a stream by naming the `profile_id` it acts as, the `device_id` to play on, and the `title_id` to watch. Starting a session is the most heavily guarded operation in the system, and its gates are evaluated as an ordered cascade. First the existence of every referenced resource is confirmed left to right; a miss yields `ERR_NOT_FOUND`. The account that owns the profile (named by the profile's `account_id`) must be `ACTIVE`, the profile itself must be `ACTIVE`, and the device must be `REGISTERED` — a request against a state that forbids the start surfaces as `ERR_INVALID_STATE`. Cross-account coherence is then enforced: the named device must belong to the same account as the profile, and a device drawn from a different account is rejected with `ERR_CROSS_ACCOUNT_REFERENCE`.

The parental gates come next. The rating gate requires the title's `maturity_rating` to be no higher on the ordered scale than the profile's `max_rating_allowed`; a title that sits above the ceiling is blocked with `ERR_RATING_BLOCKED`. The curfew gate applies when the profile has a control envelope: if the current clock-minute falls inside the curfew window (open at `curfew_start_min` inclusive, closed at `curfew_end_min` exclusive, wrapping past midnight when the end precedes the start), the start is blocked with `ERR_CURFEW_BLOCKED`. The daily-limit gate also applies only when a control sets a positive `daily_watch_limit_minutes`: the profile's `daily_watch_minutes_used` plus the title's `runtime_minutes` must be no greater than `daily_watch_limit_minutes`, and a start that would push the projected total past the allowance is blocked with `ERR_DAILY_LIMIT_EXCEEDED`.

Two utilization gates close the cascade. The device single-occupancy gate forbids a second concurrent stream on the same device whose viewing window would overlap: the target device must have no other `ACTIVE` StreamSession whose projected interval — from that session's `started_at_min` up to but not including `started_at_min` plus that session's title's `runtime_minutes` — covers the new session's start minute. The interval is half-open, so a session that begins exactly at the minute another session's interval ends does not collide; a genuine overlap is rejected with `ERR_DEVICE_BUSY`. Finally the concurrent-cap gate requires `active_stream_count` to be strictly below the plan's `concurrent_stream_cap`; an account already at its cap is rejected with `ERR_CONCURRENT_CAP_REACHED`. When every gate passes, a new session is created in `ACTIVE` status, its `started_at_min` is stamped as the current minutes-after-UTC-midnight from the system clock, `active_stream_count` is incremented by one, and `ad_breaks_served` is computed for the session.

The ad-break count is fixed at session start. On any plan whose `ad_free` flag is true, `ad_breaks_served` is 0 regardless of runtime. On an ad-supported plan, the session earns one pre-roll break before playback plus one mid-roll break for every full 30 minutes of the title's `runtime_minutes` — that is, one plus the runtime divided by 30 and rounded down to a whole number. A runtime of exactly a multiple of 30 yields that many mid-rolls; one minute short of a multiple yields one fewer.

Stopping a session drives it from `ACTIVE` to `ENDED`, may be requested only while it is `ACTIVE`, computes the session's `minutes_watched`, folds that figure into the profile's `daily_watch_minutes_used`, and decrements `active_stream_count` by one. The attributed minutes are derived from elapsed clock time, clamped to the title's runtime. If the stop occurs on the same UTC clock-day as the start — that is, the current minute-of-day is at or after the session's `started_at_min` — the elapsed time is the current minute-of-day minus `started_at_min`. If the stop falls after a UTC-midnight rollover — the current minute-of-day is below `started_at_min` — the elapsed time is 1440 minus `started_at_min`, plus the current minute-of-day; a session begun at 23:50 (minute 1430) and stopped at 00:10 (minute 10) thus elapses 20 minutes, never a negative number. The `minutes_watched` is that elapsed figure floored at 0 and capped at the title's `runtime_minutes`, and it is folded into the profile's running total without any further truncation — the daily limit is enforced only at the start gate, so a session that was allowed to start can never push the profile's used minutes past its limit when it folds in.

### 3.7. Offline Downloads

A `ProfileUser` requests an offline copy by naming the consuming `profile_id`, the licensed `device_id`, the `title_id`, and an optional `quality` that defaults to `SD`. A download may be requested only while the owning account is `ACTIVE` and the profile is `ACTIVE`, only for a title whose `downloadable` flag is true (otherwise `ERR_TITLE_NOT_DOWNLOADABLE`), and only onto a device that is `REGISTERED` and belongs to the same account as the profile — a device from another account is rejected with `ERR_CROSS_ACCOUNT_REFERENCE`. Requesting `HD` quality requires both that the current plan's `hd_offline_allowed` flag is true and that the device's `supports_hd` flag is true; an HD request that fails either condition is rejected with `ERR_HD_NOT_ALLOWED`. The download also counts against the profile's quota: the profile's combined count of `DOWNLOADING` and `READY` downloads must be below the plan's `download_quota_per_profile`, and a profile already at its quota is rejected with `ERR_DOWNLOAD_QUOTA_REACHED`. A new download starts in `DOWNLOADING` status, and its `size_mb` is computed from the title's `license_size_mb`: passed through unchanged at `SD`, and doubled at `HD`.

Completing a download drives it from `DOWNLOADING` to `READY` and stamps its `license_expires_at` to the current clock plus the offline-license window. Deleting a download is permitted from either `DOWNLOADING` or `READY`, drives it to `DELETED`, and frees one slot of the profile's download quota. A `READY` download whose license window the clock has crossed is swept to `EXPIRED` during a clock advance with sweeps enabled, likewise freeing a quota slot. Both `EXPIRED` and `DELETED` are terminal states for a download.

### 3.8. Family Invites and the Seat Hold

Growing the household past its founding profiles runs through invites, which deliberately fork into four divergent endings. An owner sends an invite by naming the inviting `account_id` and the `invitee_email`; sending mints a single-use `token` and an `expires_at` set to send-time plus the invite time-to-live, and debits a per-seat `hold_amount_cents` as a hold against the account's `wallet_credit_cents`. Sending requires the wallet to hold at least the per-seat amount; insufficient credit is rejected with `ERR_INSUFFICIENT_CREDIT`. A fresh invite begins in `PENDING` status. Invites for an account can be listed.

The four endings differ precisely in what happens to the seat hold and whether a profile is born. Accepting an invite is an anonymous, token-bearing action: it is allowed only while the invite is `PENDING`, only when the `token` in the request body matches the invite's minted `token`, only while the current clock is still before `expires_at`, only while the owning account is `ACTIVE`, and only while the account's non-`ARCHIVED` profile count is still below the plan's `max_profiles`. An accept that arrives after expiry or with a mismatched token is rejected with `ERR_INVITE_EXPIRED`; an accept that would overflow the profile cap is rejected with `ERR_PROFILE_CAP_REACHED`. A successful accept mints a brand-new profile on the account with `kind` `ADULT` and `ACTIVE` status, records that profile's id in the invite's `created_profile_id` field, and — unlike the other three endings — commits the seat hold: the held `hold_amount_cents` stays debited from the wallet as the permanent seat fee rather than being returned. Accepting drives the invite to the terminal `ACCEPTED` state.

The other three endings all release the hold back to `wallet_credit_cents` and create no profile. Declining is the other anonymous, token-bearing action: allowed only while the invite is `PENDING` and only when the supplied `token` matches, it releases the hold and drives the invite to `DECLINED`. Revoking is the owner's cancellation of a still-`PENDING` invite: it releases the hold and drives the invite to `REVOKED`, and the same revoke-with-release is what the account-close cascade applies to every pending invite. Expiry is the clock's doing: when a clock advance runs sweeps and crosses a pending invite's `expires_at`, the invite is moved to `EXPIRED` and its hold is released. All four terminal endings — `ACCEPTED`, `DECLINED`, `EXPIRED`, `REVOKED` — are reached only from `PENDING`, and a request to act on an invite that is no longer pending is rejected with `ERR_INVALID_STATE`.

### 3.9. Cross-Device Watch Progress

Resume-anywhere is modeled as a watch-progress row, upserted by a `ProfileUser`. The upsert names the `profile_id`, the `title_id`, the last synced `position_min` (a non-negative whole-minute position), and the `last_device_id` that reported it. At most one row may exist per profile-and-title pair, so a second upsert against the same pair replaces the first rather than duplicating it; a collision that the system treats as a duplicate surfaces as `ERR_DUPLICATE`. The provenance device named by `last_device_id` is validated to belong to the profile's own account — a device from a different account is rejected with `ERR_CROSS_ACCOUNT_REFERENCE` — while the title is global and needs no such check. On each upsert the row's `completed` flag is recomputed to true once `position_min` reaches the title's `runtime_minutes`, and false otherwise. Watch-progress rows can be read individually or listed and filtered.

### 3.10. Reads, Listing, and Validation Ordering

Every collection in the system can be read back. Single resources are fetched by id; collections are listed with pagination and, where noted, narrowed by a `status` filter or by the foreign keys that point into them — stream sessions and downloads accept `profile_id`, `device_id`, and `title_id` filters, watch-progress accepts `profile_id` and `title_id` filters, and the account-scoped lists of profiles, devices, and invites accept a `status` filter alongside `limit` and `offset`.

Across every endpoint the validations are applied in a fixed priority order so that a request failing several checks reports the most fundamental failure. Authentication comes first: a missing or malformed `X-User-ID`/`X-User-Role` pair on a non-token endpoint is rejected with `ERR_UNAUTHENTICATED`. Role permission is checked next, rejecting a disallowed role with `ERR_FORBIDDEN_ROLE`, followed by resource ownership for entity-backed roles, rejecting a non-owner with `ERR_NOT_RESOURCE_OWNER`. Existence of every referenced id is then validated left to right with `ERR_NOT_FOUND`, after which state legality is checked with `ERR_INVALID_STATE`, and then — on the plan-change and invoice writes — the optimistic-concurrency check raises `ERR_STALE_ACCOUNT_VERSION` on a version mismatch. Cross-account referential coherence (`ERR_CROSS_ACCOUNT_REFERENCE`) is enforced ahead of the business-specific gates. The streaming gates then evaluate rating (`ERR_RATING_BLOCKED`), curfew (`ERR_CURFEW_BLOCKED`), daily limit (`ERR_DAILY_LIMIT_EXCEEDED`), and device occupancy (`ERR_DEVICE_BUSY`) in that order. The remaining business-constraint gates follow — HD eligibility (`ERR_HD_NOT_ALLOWED`), downloadability (`ERR_TITLE_NOT_DOWNLOADABLE`), uniqueness (`ERR_DUPLICATE`), the concurrent-stream cap (`ERR_CONCURRENT_CAP_REACHED`), the per-profile download quota (`ERR_DOWNLOAD_QUOTA_REACHED`), the profile cap (`ERR_PROFILE_CAP_REACHED`), and the device cap (`ERR_DEVICE_CAP_REACHED`) — alongside the invite-temporal check (`ERR_INVITE_EXPIRED`) and the fiscal-sufficiency check (`ERR_INSUFFICIENT_CREDIT`). Field-level schema validation — required fields present, enums within their allowed sets, integers within their declared ranges — is the lowest-priority check and surfaces as `ERR_INVALID_REQUEST` only once the structural and authorization checks above it have passed.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify, transition, or upsert an existing resource return `200 OK`. The clock-advance seam, which mutates system state rather than returning a resource, also returns `200 OK`. Request and response payloads are not reproduced here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/subscription-plans` | Create a subscription plan tier | PlatformAdmin |
| GET | `/subscription-plans/{id}` | Fetch a subscription plan | PlatformAdmin, AccountOwner, ProfileUser |
| GET | `/subscription-plans/{id}/accounts` | List Accounts bound to this plan | PlatformAdmin |
| GET | `/subscription-plans/{id}/plan-changes` | List PlanChanges that moved an Account onto this plan | PlatformAdmin, AccountOwner |
| POST | `/titles` | Create a catalog title | PlatformAdmin |
| GET | `/titles/{id}` | Fetch a title | PlatformAdmin, AccountOwner, ProfileUser |
| POST | `/accounts` | Create a family-plan account and open the first billing period | AccountOwner |
| GET | `/accounts/{id}` | Fetch an account with counters and billing fields | AccountOwner, PlatformAdmin |
| POST | `/accounts/{id}/suspend` | Suspend an account; end live streams | AccountOwner |
| POST | `/accounts/{id}/reactivate` | Reactivate a suspended account; debit one period of credit | AccountOwner |
| POST | `/accounts/{id}/close` | Close an account; cascade ends, revokes, deletes, and final invoice | AccountOwner |
| POST | `/accounts/{id}/invoice` | Invoice the current open billing period | AccountOwner |
| POST | `/accounts/{id}/plan-changes` | Change the account's plan mid-period | AccountOwner |
| GET | `/accounts/{id}/plan-changes` | List an account's plan changes in creation order | AccountOwner, PlatformAdmin |
| POST | `/profiles` | Create a profile on an account | AccountOwner |
| GET | `/profiles/{id}` | Fetch a profile with computed ceiling and usage | AccountOwner, ProfileUser, PlatformAdmin |
| POST | `/profiles/{id}/archive` | Archive a profile; cascade download deletion | AccountOwner |
| POST | `/profiles/{id}/parental-control` | Set or replace a profile's parental control | AccountOwner |
| GET | `/profiles/{id}/parental-control` | Fetch a profile's parental control | AccountOwner, ProfileUser, PlatformAdmin |
| GET | `/accounts/{id}/profiles` | List profiles on an account | AccountOwner, PlatformAdmin |
| POST | `/invites` | Send a family-member invite; place a seat hold | AccountOwner |
| GET | `/accounts/{id}/invites` | List invites for an account | AccountOwner, PlatformAdmin |
| POST | `/invites/{id}/accept` | Accept an invite via token; mint a profile and commit the hold | Anonymous |
| POST | `/invites/{id}/decline` | Decline an invite via token; release the hold | Anonymous |
| POST | `/invites/{id}/revoke` | Revoke a pending invite; release the hold | AccountOwner |
| POST | `/devices` | Register a device on the account | AccountOwner |
| GET | `/accounts/{id}/devices` | List devices on an account | AccountOwner, PlatformAdmin |
| POST | `/devices/{id}/deregister` | Deregister a device; cascade download deletion | AccountOwner |
| POST | `/stream-sessions` | Start a streaming session | ProfileUser |
| POST | `/stream-sessions/{id}/stop` | Stop a streaming session; attribute watch minutes | ProfileUser |
| GET | `/stream-sessions/{id}` | Fetch a stream session | AccountOwner, ProfileUser, PlatformAdmin |
| GET | `/stream-sessions` | List stream sessions, filterable | AccountOwner, ProfileUser, PlatformAdmin |
| POST | `/downloads` | Request an offline download | ProfileUser |
| POST | `/downloads/{id}/complete` | Mark a download ready; stamp license expiry | ProfileUser |
| DELETE | `/downloads/{id}` | Delete a download; free a quota slot | ProfileUser |
| GET | `/downloads/{id}` | Fetch a download | AccountOwner, ProfileUser, PlatformAdmin |
| GET | `/downloads` | List downloads, filterable | AccountOwner, ProfileUser, PlatformAdmin |
| PUT | `/watch-progress` | Upsert cross-device playback position | ProfileUser |
| GET | `/watch-progress/{id}` | Fetch a watch-progress row | AccountOwner, ProfileUser, PlatformAdmin |
| GET | `/watch-progress` | List watch-progress rows, filterable | AccountOwner, ProfileUser, PlatformAdmin |
| POST | `/_clock/advance` | Advance the system clock; optionally run expiry and rollover sweeps | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_CROSS_ACCOUNT_REFERENCE` | 409 Conflict |
| `ERR_RATING_BLOCKED` | 403 Forbidden |
| `ERR_CURFEW_BLOCKED` | 409 Conflict |
| `ERR_DAILY_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_DEVICE_BUSY` | 409 Conflict |
| `ERR_HD_NOT_ALLOWED` | 409 Conflict |
| `ERR_TITLE_NOT_DOWNLOADABLE` | 409 Conflict |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_CONCURRENT_CAP_REACHED` | 409 Conflict |
| `ERR_DOWNLOAD_QUOTA_REACHED` | 409 Conflict |
| `ERR_PROFILE_CAP_REACHED` | 409 Conflict |
| `ERR_DEVICE_CAP_REACHED` | 409 Conflict |
| `ERR_INSUFFICIENT_CREDIT` | 402 Payment Required |
| `ERR_INVITE_EXPIRED` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
</content>
</invoke>
