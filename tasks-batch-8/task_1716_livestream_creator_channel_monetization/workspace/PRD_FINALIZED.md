# Livestream Creator Monetization API — Product Requirements Document

## 1. Introduction

Creator channels on mainstream streaming platforms earn through a blend of subscriptions, viewer tips, advertising revenue shares, and sponsored campaign work, and every dollar travels through platform fees, tax withholding, and compliance gates before it can be paid out. This document specifies the API for a creator monetization backend that manages the full business loop: channel onboarding and tax-form compliance, an append-only revenue ledger with month-end recognition, threshold-gated payouts with a full settlement lifecycle, subscriber tiers with limited-inventory merchandise perks, a moderation staff built on progressive viewer discipline, content strikes with a segregated two-round appeals process, sponsorship deals with deliverable verification and disclosure tracking, and stream scheduling with multi-platform simulcast rights. All resources are mounted under `/api`.

Two design commitments shape every workflow in this document. First, money is handled as an immediately consistent ledger: every mutation and every cascade it triggers is visible in the response of the same request, balances are conserved through compensating pairs, and revenue recognition runs in two variants — a provisional figure computed at ingestion and a final figure computed at month settlement. Second, time is logical rather than wall-clock: the server boots at a fixed instant, an administrative capability moves the clock forward, and a single ops checkpoint advances month settlement, expiries, renewals, no-shows, deliverable misses, and deal completions in a pinned step order so that every temporal rule in this document is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or carrying an empty value for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A caller whose role is not listed on the endpoint — or, on the transition-style endpoints, whose role is not permitted for the specific `action` requested — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Six roles exist, spelled exactly as follows:

- `PlatformAdmin` — platform operations: channel onboarding, revenue ingestion, chargebacks, payout processing, simulcast approval, ops runs, and the logical clock.
- `Creator` — the channel owner, managing tiers, moderators, deals, deliverables, streams, appeals, and payout requests.
- `Moderator` — channel moderation staff issuing enforcement actions within granted scopes.
- `Sponsor` — the brand counterparty accepting deals and verifying or disputing deliverables.
- `TrustAgent` — the trust-and-safety issuer who files content strikes and adjudicates tax forms; a `TrustAgent` never resolves appeals.
- `AppealsOfficer` — the independent reviewer who resolves strike appeals and may reverse moderation actions.

Role identity binds `X-User-ID` to persisted entities in two different ways. When `X-User-Role` is `Creator`, `X-User-ID` is the `id` of the acting `Channel`; ownership checks on any resource that references a channel compare the resource's channel foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_CHANNEL_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `Moderator`, `X-User-ID` is the `id` of the acting `Moderator`; in particular, the invite-acceptance transition requires the caller's `X-User-ID` to equal the invited moderator's `id`, and a mismatch is likewise rejected with `ERR_CHANNEL_OWNERSHIP_MISMATCH`.

When `X-User-Role` is `PlatformAdmin`, `TrustAgent`, or `AppealsOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `issued_by_user_id` on a strike at issuance or as `resolved_by_user_id` when an appeal is resolved — but does not compare it to any entity's `id`. When `X-User-Role` is `Sponsor`, `X-User-ID` is also opaque at the entity level, but sponsor-privileged actions carry a business identity rule: the caller's `X-User-ID` must equal the deal's `sponsor_ref`, and a mismatch is rejected with `ERR_SPONSOR_MISMATCH` (HTTP 403).

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

List endpoints accept two query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. Results are sorted by `created_at` ascending unless a subsection states otherwise. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a caller can always tell how many records exist in total and whether further pages remain.

### 2.4. Resource Identity, Timestamps, and Path Resolution

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC values rendered with three fractional digits. `version` starts at 1 when the resource is created and increments by exactly 1 on every mutation of that resource; `updated_at` is refreshed to the logical clock time of each mutation.

One entity is the deliberate exception. A `RevenueEvent` is an append-only ledger entry: it carries only `id` and `created_at` from the common set, its business content is immutable once ingested, and it has neither `updated_at` nor `version`. Corrections to the ledger are never edits — they are new events, as the chargeback workflow in §3.2 describes.

All collections are top-level under `/api`; parent-child relationships are expressed through foreign-key references on the child and through nested creation paths. When a URL contains several path identifiers, they are validated strictly left to right: each identifier must exist, and each nested identifier must belong to the parent implied by the path before the next identifier is examined. The same rule applies to body-referenced identifiers — a payload naming a `viewer_id`, `tier_id`, `stream_id`, or `reverses_event_id` that does not exist, or that belongs to a different parent than the path implies, is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.5. The Logical Clock and the Ops Checkpoint

The server maintains a single logical clock. At startup the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall time. A `PlatformAdmin`-only test-driving capability, `POST /api/_clock/set_current_utc`, replaces the logical clock with the supplied `to_iso8601` instant and returns the resulting `current_utc`; every piece of date arithmetic in this document — deadlines, windows, grace periods, expiries, settlement months — derives from this clock.

A second `PlatformAdmin`-only capability, `POST /api/ops/run`, advances the ops checkpoint. Each run executes the following steps in this pinned order:

1. **Month settlement.** `PENDING` revenue events whose settlement month is strictly earlier than the clock's current calendar month are settled to `CLEARED`, and each settled event's final net is recomputed under the volume-rebate rule of §3.2.
2. **Strike expiry.** Strikes in `ISSUED` or `UPHELD` status whose expiry instant has been reached or passed become `EXPIRED`; strikes `UNDER_APPEAL` are exempt, because a pending appeal tolls the window. Channel posture is recomputed after each expiry.
3. **Tax-form expiry.** `VERIFIED` tax forms whose `expires_on` has been reached or passed become `EXPIRED`, with the posture recomputation and payout-hold cascade of §2.7 and §3.1.
4. **Simulcast-grant expiry.** `APPROVED` grants whose `window_end` has been reached or passed become `EXPIRED`.
5. **Stream no-shows.** Streams still `SCHEDULED` more than thirty minutes past their scheduled start become `NO_SHOW`.
6. **Deliverable misses.** Deliverables still `SCHEDULED` whose `due_at` is in the past become `MISSED`, incrementing the deal's `miss_count` and triggering the breach cascade of §3.7 when the count reaches three.
7. **Perk expiry.** Merch grants in `PENDING` or `FAILED` status whose `due_at` is in the past become `EXPIRED`.
8. **Subscription renewal and lapse.** Each `ACTIVE` subscription whose `current_period_end` has been reached or passed is renewed per §3.4 — processed in ascending `current_period_end` order with ties broken by ascending `created_at` — and each `PAST_DUE` subscription whose seven-day grace after `current_period_end` has elapsed becomes `EXPIRED`.
9. **Deal completion.** `ACTIVE` deals that qualify under §3.7 become `COMPLETED`.
10. **Moderation expiry.** `ACTIVE` `TIMEOUT` moderation actions whose `expires_at` has been reached or passed become `EXPIRED`, and viewer standing is recomputed.

A run also increments `ops_run_index`, which starts at 0, and its response reports the counters `ops_run_index`, `events_cleared`, `strikes_expired`, `tax_forms_expired`, `grants_expired`, `streams_no_show`, `deliverables_missed`, `perks_expired`, `subscriptions_renewed`, `subscriptions_expired`, `deals_completed`, and `payouts_released` — the last of these counting held payouts released back to `SCHEDULED` by the posture recomputations the run triggered.

### 2.6. Money, Rounding, and Ledger Conservation

All monetary values are integer cents; there are no fractional cents anywhere in the API, and every rounding is **round half up** — a half cent rounds away from zero. Where a rule aggregates a per-event figure, the rounding order is pinned: each event's figure is rounded first, and the rounded figures are then summed. The alternative order — summing raw figures and rounding once — can differ by cents and is never used.

Each channel carries three computed balances. `balance_pending_cents` is the sum of provisional `net_cents` over the channel's revenue events still in `PENDING` status. `balance_payable_cents` is the sum of final net over the channel's `CLEARED` events — with `CHARGEBACK` nets contributing negative amounts — minus the `amount_cents` of every payout of the channel in `SCHEDULED`, `PROCESSING`, `FAILED`, or `HELD` status, minus the `amount_cents` of every `PAID` payout. `lifetime_paid_cents` is the sum of `net_transfer_cents` over the channel's `PAID` payouts.

These definitions yield a conservation invariant: payable balance plus the amounts reserved by in-flight payouts plus lifetime paid plus the accumulated `fee_cents` of `PAID` payouts equals the cumulative cleared net revenue, with reversed originals already subtracted at reversal time. Two compensating pairs keep the invariant intact across the payout lifecycle — opening a payout deducts exactly `amount_cents` from the payable balance, and cancelling that payout restores exactly `amount_cents`, so an open followed by a cancel leaves the payable balance unchanged.

### 2.7. Channel Monetization Posture

A channel's `monetization_posture` is a derived state, recomputed immediately after every strike transition, every tax-form submission or transition, and every ops-run expiry that touches the channel. Three states exist. `STANDARD` requires the channel's active strike weight to be exactly zero **and** the channel's current tax form to be `VERIFIED`. `SUSPENDED` applies whenever the active strike weight reaches three or more — the comparison is inclusive. Everything else is `RESTRICTED`, which is also the posture every channel is born with, since no channel has a verified tax form at onboarding.

The canonical active strike weight is a hard-window sum: over the channel's strikes in `ISSUED`, `UNDER_APPEAL`, or `UPHELD` status whose `expires_at` is still in the future, add each strike's severity weight — one for `MINOR`, two for `MAJOR`, three for `SEVERE`. A single `SEVERE` strike therefore suspends a channel by itself, as does one `MINOR` plus one `MAJOR`. The companion `active_strike_count` counts the channel's strikes currently in `ISSUED`, `UNDER_APPEAL`, or `UPHELD` status, and `trust_score_bp` is ten thousand minus 2,500 basis points per unit of active strike weight, floored at zero.

Posture is not merely a label — it drives the payout pipeline through a cascade. When a channel leaves `STANDARD`, every payout of that channel currently `SCHEDULED` is moved to `HELD`: the drop to `RESTRICTED` stamps each held payout's `hold_reason` as `TAX_FORM` or `POSTURE` according to the cause, and the drop to `SUSPENDED` always stamps `POSTURE`. Release is the mirror image. When a tax form is verified and the resulting posture is not `SUSPENDED`, payouts held with `hold_reason` `TAX_FORM` return to `SCHEDULED`; when a strike reversal or expiry returns the posture to `STANDARD`, payouts held with `hold_reason` `POSTURE` return to `SCHEDULED`. Any release requires the posture to be non-`SUSPENDED` and the current tax form to be `VERIFIED`, and a released payout's `hold_reason` is cleared to `NONE`.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each keyed on the version of a parent entity:

- `PATCH /api/channels/{channel_id}/payout-settings` requires a non-optional `expected_channel_version` input carrying the client's last observed `version` of the channel.
- `POST /api/channels/{channel_id}/tax-forms` requires the same `expected_channel_version` input, since a submission supersedes the channel's current form.
- `POST /api/deliverables/{deliverable_id}/reschedule` requires a non-optional `expected_deliverable_version` input carrying the client's last observed `version` of the deliverable.

On each of these endpoints, if the supplied expected version does not match the parent entity's current `version` — because another writer has advanced that version since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the entity before re-issuing. Endpoints not listed here take no version field at all.

### 2.9. Validation Order of Precedence

When several checks could reject the same request, they are evaluated in the following fixed priority order, so the error a caller sees is deterministic:

1. **Authentication.** `X-User-Role` and `X-User-ID` must be present and non-empty — otherwise `ERR_UNAUTHENTICATED`.
2. **Request well-formedness.** The body must parse, required fields must be present, enums must be in their declared sets, and integer and temporal ranges must hold: a `TIMEOUT` action carries `duration_minutes` between 1 and 10,080 minutes (one week) inclusive while a `BAN` must omit it, a stream's `scheduled_end` is strictly after its `scheduled_start`, a grant's `window_end` is strictly after its `window_start`, and a deliverable's `due_at` lies within its deal's flight — otherwise `ERR_INVALID_REQUEST`.
3. **Endpoint and per-action authorization.** The role must be listed on the endpoint, and on transition endpoints it must also be permitted for the requested `action` — otherwise `ERR_UNAUTHORIZED`.
4. **Existence.** Path identifiers are validated left to right, then body-referenced identifiers — otherwise `ERR_NOT_FOUND`.
5. **Ownership and actor identity.** A `Creator` caller must own the channel in the path, a `Sponsor` caller must match the deal's `sponsor_ref`, and a moderator accepting an invite must be that moderator — otherwise `ERR_CHANNEL_OWNERSHIP_MISMATCH` (sponsor mismatches surface as `ERR_SPONSOR_MISMATCH` under rule 19).
6. **State admissibility.** The target entity must be in a state that admits the requested transition — wrong-from-state, terminal lockdown, and duplicate or repeat triggers all fail here with `ERR_INVALID_STATE`. At the same tier, the payout retry cap is a state-level check: a retry while `retry_count` is already 3 fails with `ERR_RETRY_LIMIT_REACHED`, and this cap fires before any fiscal gate.
7. **Suspension gates.** A `SUSPENDED` channel blocks exactly five operations — payout opening, payout retry, deal activation, deliverable performance, and simulcast-grant approval — each rejected with `ERR_CHANNEL_SUSPENDED`.
8. **Segregation of duties.** The officer resolving a strike appeal must not be the agent who issued the strike — otherwise `ERR_SELF_REVIEW_FORBIDDEN`.
9. **Progressive discipline.** A `BAN` requires the prior-timeout history of §3.5 — otherwise `ERR_PROGRESSIVE_DISCIPLINE`.
10. **Appeal window.** An appeal filed after the strike's `appeal_deadline` is rejected with `ERR_APPEAL_WINDOW_CLOSED`.
11. **Appeal rounds.** An appeal filed when `appeal_round` has already reached the cap of 2 is rejected with `ERR_APPEAL_LIMIT_REACHED`. The window check outranks the round check, so an appeal that violates both reports the closed window.
12. **Stream window overlap.** A new stream must not overlap a non-terminal sibling under the half-open rule of §3.8 — otherwise `ERR_STREAM_WINDOW_CONFLICT`.
13. **Simulcast buffer.** Approval must preserve the twenty-four-hour separation rule of §3.8 — otherwise `ERR_SIMULCAST_BUFFER_CONFLICT`.
14. **Category exclusivity.** Deal activation must not collide with a same-category sibling under the closed-interval rule of §3.7 — otherwise `ERR_CATEGORY_EXCLUSIVITY_CONFLICT`.
15. **Deliverable timeliness.** Performance after `due_at` is rejected with `ERR_DELIVERABLE_OVERDUE`.
16. **Simulcast coverage.** Starting a simulcast stream without a fully covering `APPROVED` grant is rejected with `ERR_SIMULCAST_GRANT_MISSING`.
17. **Optimistic concurrency.** The three OCC-guarded writes of §2.8 are rejected with `ERR_STALE_VERSION` on a version mismatch.
18. **Uniqueness.** Channel handles are unique across all channels — a duplicate is rejected with `ERR_INVALID_REQUEST`; at most one `ACTIVE` tier per `tier_code` exists per channel — a conflicting creation or reactivation is rejected with `ERR_TIER_CODE_IN_USE`; and at most one payout per channel is in flight in `SCHEDULED`, `PROCESSING`, `FAILED`, or `HELD` status — a conflicting open is rejected with `ERR_PAYOUT_IN_FLIGHT`.
19. **Sponsor identity.** Sponsor-privileged actions require the caller's `X-User-ID` to equal the deal's `sponsor_ref` — otherwise `ERR_SPONSOR_MISMATCH`.
20. **Moderator gating.** The issuing moderator must be `ACTIVE` — otherwise `ERR_MODERATOR_NOT_ACTIVE` — and must hold the scope matching the action kind — otherwise `ERR_MODERATOR_SCOPE_MISSING`.
21. **Perk inventory.** Fulfillment against an exhausted tier is rejected with `ERR_PERK_INVENTORY_EXHAUSTED`.
22. **Disclosure before verification.** Sponsor verification of an undisclosed deliverable is rejected with `ERR_DISCLOSURE_REQUIRED`.
23. **Cross-reference consistency.** The viewer and tier of a new subscription must belong to the path channel, as must the stream referenced by a deliverable belong to the deal's channel — mismatches surface as `ERR_NOT_FOUND` — and a subscription created or recovered for a `BANNED` viewer is rejected with `ERR_VIEWER_BANNED`.
24. **Tax gate.** Opening or retrying a payout while the channel's current tax form is missing or not `VERIFIED` is rejected with `ERR_TAX_FORM_NOT_VERIFIED` (HTTP 402).
25. **Non-empty sweep.** Opening a payout with no eligible `CLEARED` revenue event is rejected with `ERR_NO_ELIGIBLE_REVENUE` (HTTP 422); a zero-balance channel fails here, before the threshold check.
26. **Threshold gate.** Opening a payout while `balance_payable_cents` is strictly below `payout_threshold_cents` is rejected with `ERR_BELOW_PAYOUT_THRESHOLD` (HTTP 422); exactly-at-threshold is eligible, because the boundary is inclusive.

## 3. Business Logic & Workflows

### 3.1. Channel Onboarding and Tax Compliance

A `PlatformAdmin` onboards a new creator channel by supplying its unique `handle`, its public `display_name`, and its `home_platform` — one of `TWITCH` or `YOUTUBE`. Two payout preferences may be set at creation: `payout_schedule`, one of `WEEKLY`, `BIWEEKLY`, or `MONTHLY` and defaulting to `MONTHLY`, and `payout_threshold_cents`, the minimum payable balance required to open a payout, defaulting to 10,000 cents (one hundred dollars). Handles are unique across all channels, so a duplicate is rejected with `ERR_INVALID_REQUEST`. A freshly created channel starts with `monetization_posture` `RESTRICTED` — no verified tax form exists yet — with all balances at zero and `version` 1.

The channel owner may later adjust the two payout preferences through the payout-settings update, passing whichever of `payout_schedule` and `payout_threshold_cents` should change plus the OCC field `expected_channel_version` described in §2.8. A successful update increments the channel's `version` by 1; a stale expected version is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the caller to re-read the channel before its settings may replace the current ones.

Payouts are impossible until the channel's taxes are in order, and the tax lifecycle runs on `TaxForm` records. The owner submits a form with its `form_type` — `W9` for domestic creators, `W8BEN` or `W8BENE` for foreign persons and entities — together with the `legal_name` on the form and the `tax_id_last4` of the tax identifier, plus the OCC field `expected_channel_version`. Submission is **supersession**: the new form is born `SUBMITTED`, its `submitted_at` is stamped with the logical clock, the channel's `tax_form_current_id` swings to it, its `prior_form_id` chains back to the previously current form (null for a channel's first submission), the channel's `version` increments by 1, and posture is recomputed. A rejected form is never resurrected in place — it remains `REJECTED` as history while a new `SUBMITTED` row takes over as current, so the `REJECTED`-to-`SUBMITTED` arc is realized by supersession rather than by editing the old row. The form list accepts `channel_id`, `tax_status`, and `prior_form_id` filters, the last of which locates the supersession successor of a given form.

Adjudication belongs to a `TrustAgent`. Verification moves a `SUBMITTED` form to `VERIFIED`, stamps `verified_at`, computes `expires_on` as exactly 365 days after `verified_at`, recomputes the channel's posture, and — provided the posture is not `SUSPENDED` — releases each of the channel's payouts held with `hold_reason` `TAX_FORM` back to `SCHEDULED`, clearing their `hold_reason` to `NONE`. Rejection requires a `rejection_reason`, which is recorded on the form as it moves to `REJECTED`. Forms do not stay valid forever: when an ops run finds the clock at or past the current form's `expires_on`, that form becomes `EXPIRED`, the posture is recomputed — dropping the channel to `RESTRICTED` when no other `VERIFIED` form remains — and the §2.7 cascade moves the channel's `SCHEDULED` payouts to `HELD` with `hold_reason` `TAX_FORM`.

### 3.2. Revenue Ingestion, Month-End Recognition, and Chargebacks

Revenue enters the ledger through platform-side ingestion: a `PlatformAdmin` posts each event with its `kind` — `SUBSCRIPTION`, `TIP`, `AD_SHARE`, `SPONSORSHIP`, or `CHARGEBACK` — its `gross_cents`, its `platform_fee_bps` expressed in basis points of gross between 0 and 10,000, and the business timestamp `occurred_at`. The `settlement_month` is derived from `occurred_at` as its `YYYY-MM` label, and that label drives month-end settlement. Only `CHARGEBACK` events may carry a negative `gross_cents`, and only `CHARGEBACK` events carry `reverses_event_id`, a self-referential link to the earlier event being reversed; for that kind the link is required, and for every other kind it must be absent. The revenue-event list accepts `channel_id`, `kind`, `recognition_status`, `settlement_month`, and `reverses_event_id` filters — the last of which finds the chargeback of a given event.

Recognition runs in two variants, and the difference between them is where the ledger earns its name. **At ingestion** a non-chargeback event is born `PENDING` with a *provisional* `net_cents`: the event's `platform_fee_bps` is subtracted from ten thousand to obtain the creator's share in basis points, `gross_cents` is multiplied by that share and divided by ten thousand, and the result is rounded half up to whole cents. The provisional figure never applies the volume rebate, and the event's net is added to the channel's `balance_pending_cents`. **At month settlement** — ops step 1 — each `PENDING` event whose `settlement_month` is strictly earlier than the clock's current month moves to `CLEARED`, and its *final* net is recomputed. The run first computes the month gross: the sum of `gross_cents` over the channel's non-`CHARGEBACK` events bearing that settlement month and being settled in this run. When the month gross reaches at least 5,000,000 cents (fifty thousand dollars), every event settled in that month enjoys a **volume rebate** of 250 basis points, so its effective fee is its `platform_fee_bps` reduced by 250; below the cliff the effective fee is simply `platform_fee_bps`. The final `net_cents` is then the gross multiplied by ten thousand minus the effective fee, divided by ten thousand, and rounded half up to whole cents. The rebate is a cliff applied to every event of the month, not a marginal rate — so once the threshold is crossed, identical events yield a larger final net than their provisional figure. Settlement moves money between balances in the same breath: the provisional net leaves `balance_pending_cents` and the final net lands in `balance_payable_cents`.

Chargebacks play by stricter rules. A `CHARGEBACK` event never waits for month settlement — it is ingested directly in `CLEARED` status, always uses its plain fee with no rebate, and its negative net subtracts from `balance_payable_cents` immediately. Because a chargeback is itself terminal-immutable, there is no reverse of a reverse.

Reversal of an ordinary event is a `PlatformAdmin` capability with a `reason` recorded on the request, and it is guarded by three conditions, all enforced with `ERR_CHARGEABILITY_VIOLATION` (HTTP 409): the target's `kind` must not be `CHARGEBACK`, its `recognition_status` must be `CLEARED`, and no existing `CHARGEBACK` event may already point at it through `reverses_event_id`. A valid reversal flips the original from `CLEARED` to `REVERSED` — a terminal state — and creates a new `CHARGEBACK` event whose `gross_cents` is the negation of the original's gross, whose `platform_fee_bps` equals the original's `platform_fee_bps`, whose `recognition_status` is `CLEARED`, and whose `reverses_event_id` names the original. The effect on the channel's `balance_payable_cents` then follows the §2.6 formula exactly: the original's net leaves the payable sum because the original is no longer `CLEARED`, and the chargeback's own negative net — figured under the plain-fee rule above, with no rebate — lands in the same sum immediately, so a reversal may legitimately drive `balance_payable_cents` negative.

### 3.3. Payouts: Eligibility, Opening, Settlement, and Holds

A channel owner opens a payout to sweep the eligible payable balance, and opening is the most heavily gated operation in the system. In the precedence order of §2.9: the caller must own the channel; the channel's posture must not be `SUSPENDED` (`ERR_CHANNEL_SUSPENDED`); no other payout of the channel may be in flight in `SCHEDULED`, `PROCESSING`, `FAILED`, or `HELD` status (`ERR_PAYOUT_IN_FLIGHT`); the current tax form must be `VERIFIED` (`ERR_TAX_FORM_NOT_VERIFIED`, HTTP 402); at least one eligible `CLEARED` revenue event must exist to sweep (`ERR_NO_ELIGIBLE_REVENUE`, HTTP 422 — a zero-balance channel fails here, before the threshold is ever examined); and finally `balance_payable_cents` must be at least `payout_threshold_cents` (`ERR_BELOW_PAYOUT_THRESHOLD`, HTTP 422). The threshold comparison is inclusive — a balance exactly at the threshold is eligible.

Opening a payout performs a fixed sequence of computations, and the order is pinned to remove any circularity. First, withholding is computed over the swept events: when the channel's current tax form's `form_type` is `W8BEN` or `W8BENE`, each swept event contributes thirty percent — 3,000 basis points — of its `net_cents`, rounded half up to whole cents *per event*; for a `W9` channel every event contributes zero. The payout's `withholding_cents` is the sum of those per-event amounts, and per §2.6 the per-event rounding happens before the summation. Second, the **snapshot** is taken: the channel's `balance_payable_cents` minus the payout's `withholding_cents`. Third, the transfer-fee tier is selected on that pre-fee snapshot — never on the post-fee remainder: a snapshot of at least 1,000,000 cents (ten thousand dollars) is charged 25 basis points, a snapshot of at least 100,000 cents (one thousand dollars) is charged 50 basis points, and anything smaller is charged 100 basis points. Fourth, `amount_cents` is set equal to the snapshot, `fee_cents` is the snapshot multiplied by the tier's basis points and divided by ten thousand with round-half-up to whole cents, and `net_transfer_cents` is `amount_cents` minus `fee_cents`. The new payout is born `SCHEDULED`, records the count of swept `CLEARED` events in `settled_event_count`, stamps `scheduled_for` with the creation clock time as its payout-window label, and starts with `retry_count` 0 and `failure_reason` null. In the same response, the channel's `balance_payable_cents` drops by `amount_cents` — the swept money is now reserved. The payout list accepts a `payout_status` filter.

From `SCHEDULED`, a `PlatformAdmin` drives settlement: processing moves the payout to `PROCESSING`, a successful settle moves it to `PAID` — adding `net_transfer_cents` to the channel's `lifetime_paid_cents` — and a failed settle requires a `failure_reason`, records it, and moves the payout to `FAILED`. `PAID` is terminal.

Failure is recoverable by the owner through a retry, which returns the payout from `FAILED` to `SCHEDULED`. The retry cap is a state-level gate evaluated before the fiscal gates of §2.9: when `retry_count` has already reached 3, the retry is rejected with `ERR_RETRY_LIMIT_REACHED`. Otherwise the retry re-checks only the compliance gates — the posture must not be `SUSPENDED` (`ERR_CHANNEL_SUSPENDED`) and the current tax form must be `VERIFIED` (`ERR_TAX_FORM_NOT_VERIFIED`) — because threshold and eligibility were validated once at open and the swept amount has stayed reserved the whole time. A successful retry increments `retry_count` by 1 and clears `failure_reason`.

Holds arrive from above, never from the owner. Whenever the §2.7 cascade fires — the channel leaving `STANDARD`, or the current tax form becoming `EXPIRED` or `REJECTED` — every `SCHEDULED` payout of the channel moves to `HELD` with `hold_reason` set to `TAX_FORM` or `POSTURE`; outside of a hold, `hold_reason` reads `NONE`. Release is automatic as §2.7 describes: a tax verification releases `TAX_FORM` holds when the posture is not `SUSPENDED`, and a posture returning to `STANDARD` releases `POSTURE` holds — in both cases only when the posture is non-`SUSPENDED` and the current form is `VERIFIED`, and the released payout's `hold_reason` returns to `NONE`.

The owner may also cancel, from either `SCHEDULED` or `HELD`, moving the payout to the terminal `CANCELLED`. Cancellation is the compensating half of the §2.6 pair: the channel's `balance_payable_cents` is restored by exactly `amount_cents`, leaving the ledger as if the payout had never been opened.

### 3.4. Tiers, Viewers, Subscriptions, and Perk Fulfillment

A channel's subscription business starts with its tiers. The owner creates a tier with a `tier_code` of `TIER_1`, `TIER_2`, or `TIER_3`, a `monthly_price_cents`, a `revenue_share_bps` naming the creator's share of the price in basis points — the platform fee on the resulting revenue events is the remainder out of ten thousand — and a `perk_inventory_total` sizing the tier's limited merchandise stock. A new tier is born `ACTIVE` with `perk_inventory_remaining` equal to `perk_inventory_total`, and at most one `ACTIVE` tier per `tier_code` may exist per channel: a conflicting creation, or a reactivation while a sibling with the same code is active, is rejected with `ERR_TIER_CODE_IN_USE`. Retiring a tier moves it to `RETIRED`, which blocks new subscriptions referencing it while leaving existing subscriptions untouched; reactivation returns it to `ACTIVE` under the same uniqueness gate. The tier list accepts a `tier_status` filter.

Viewers are registered under a channel by a `PlatformAdmin` with just a `handle`; a new viewer starts in `GOOD_STANDING` with `lifetime_spend_cents` at zero, the latter accumulating the gross of the viewer's paid subscription cycles and tips over time. The viewer list accepts a `standing` filter.

A subscription is started platform-side — billing is a platform concern — by posting a payload containing the `viewer_id` and the `tier_id`. Both must belong to the channel in the path (otherwise `ERR_NOT_FOUND`), the viewer's standing must not be `BANNED` (`ERR_VIEWER_BANNED`), and the tier must currently be `ACTIVE` (a `RETIRED` tier fails with `ERR_INVALID_STATE`). A successful start does five things at once: the subscription is born `ACTIVE` with `started_at` stamped from the clock; `current_period_end` is set one calendar month after `started_at`; `cycles_paid` starts at 1; the cycle-1 charges are recorded as a `SUBSCRIPTION` revenue event in `PENDING` status whose `gross_cents` is the tier's `monthly_price_cents` and whose `platform_fee_bps` is ten thousand minus the tier's `revenue_share_bps`; and a `MERCH` perk grant is created in `PENDING` status, due in fourteen days. The viewer's `lifetime_spend_cents` grows by the tier's price. The subscription list accepts `channel_id`, `viewer_id`, `tier_id`, and `sub_status` filters.

Billing health is managed through a small lifecycle. A `PlatformAdmin` may mark an `ACTIVE` subscription `PAST_DUE`, and may later recover a `PAST_DUE` subscription back to `ACTIVE` — recovery being the second place the ban gate bites, since recovering a subscription for a `BANNED` viewer is rejected with `ERR_VIEWER_BANNED`. The owner may cancel from either `ACTIVE` or `PAST_DUE`, moving the subscription to the terminal `CANCELLED`, and the viewer-ban cascade of §3.5 performs the same transition system-side. Cancellation voids the subscription's outstanding perks: grants in `PENDING` or `FAILED` move to `VOIDED`, while `FULFILLED` grants are untouched and no inventory is restored. There is no automatic expiry edge out of `ACTIVE` — a healthy subscription renews instead. The only road to the terminal `EXPIRED` runs through delinquency: an ops run expires a `PAST_DUE` subscription once the clock reaches seven days past its `current_period_end`, voiding its `PENDING` and `FAILED` grants the same way.

Renewal is ops step 8. For each `ACTIVE` subscription whose `current_period_end` has been reached or passed — processed in ascending `current_period_end` order, ties broken by ascending `created_at` — the run increments `cycles_paid` by 1, rolls `current_period_end` forward by one calendar month using same-day-of-month arithmetic clamped to the target month's length, records the new cycle's `SUBSCRIPTION` revenue event in `PENDING` status with the same gross and fee split as cycle 1, creates the cycle's `MERCH` grant in `PENDING` due fourteen days out, and adds the tier's price to the viewer's `lifetime_spend_cents`.

Merch fulfillment is the owner's workload. Every grant carries `perk_kind` `MERCH` — the limited-inventory perk granted per paid cycle — and each grant is born `PENDING` with `due_at` exactly fourteen days after its `created_at` and `failure_count` at zero, the fulfillment SLA enforced against that deadline. Fulfilling a grant requires the tier's `perk_inventory_remaining` to be greater than zero — an exhausted tier rejects the attempt with `ERR_PERK_INVENTORY_EXHAUSTED` — and on success decrements `perk_inventory_remaining` by 1 and stamps `fulfilled_at`. A failed fulfillment attempt moves the grant to `FAILED` and increments its `failure_count`; the owner may retry a `FAILED` grant back to `PENDING` only while the clock has not yet passed `due_at`, a past-SLA retry being rejected with `ERR_INVALID_STATE`. Ops step 7 sweeps grants in `PENDING` or `FAILED` whose `due_at` has passed into the terminal `EXPIRED`. Explicit voiding by the owner applies to `FULFILLED` grants and is the one compensating move in this lifecycle: it returns the unit to stock, incrementing `perk_inventory_remaining` by 1. Cascade voiding from subscription cancellation, subscription expiry, or viewer bans applies only to `PENDING` and `FAILED` grants and restores nothing. The invariant `perk_inventory_remaining` plus the count of the tier's `FULFILLED` grants equals `perk_inventory_total` holds at all times, and a subscription's grant list accepts a `perk_status` filter.

### 3.5. Moderation Staff and Progressive Viewer Discipline

Channel moderation is delegated but never anonymous. The owner invites a moderator by supplying a `moderator_handle` and the `scopes` granted — a subset of `TIMEOUT` and `BAN` — and the invitee is born `INVITED`. Acceptance is self-service and identity-checked: the transition to `ACTIVE` must be performed with an `X-User-ID` equal to that moderator's own `id`, otherwise `ERR_CHANNEL_OWNERSHIP_MISMATCH`. From `ACTIVE`, the owner may suspend a moderator — while `SUSPENDED`, the moderator may no longer issue enforcement actions — and may later reinstate them. Removal moves the moderator to the terminal `REMOVED` from either `ACTIVE` or `SUSPENDED`; it deliberately does **not** auto-reverse the moderator's existing actions, which keep whatever standing they had. A moderator's `actions_issued_count` counts their enforcement actions not currently in `REVERSED` status. The moderator list accepts a `moderator_status` filter.

Enforcement actions are issued by the owner directly or by a moderator, against a payload containing the target `viewer_id`, the `action_kind` — `TIMEOUT` or `BAN` — and a free-form `reason`. When a moderator issues the action, that moderator must be `ACTIVE` (`ERR_MODERATOR_NOT_ACTIVE`) and must hold the scope matching the action kind — a `BAN` issued without the `BAN` scope is rejected with `ERR_MODERATOR_SCOPE_MISSING`; when the owner issues it, the action's `moderator_id` stays null. Duration rules come from §2.9: a `TIMEOUT` carries `duration_minutes` from 1 to 10,080, while a `BAN` omits it. Issuance stamps `issued_at` from the clock; a `TIMEOUT` computes `expires_at` as `issued_at` plus its duration, while a `BAN` has a null `expires_at` and never auto-expires. Every issuance recomputes the viewer's standing and increments the issuing moderator's `actions_issued_count` by 1.

Discipline is **progressive**: a channel may not ban a viewer out of the blue. Issuing a `BAN` requires at least two prior `TIMEOUT` actions on the same channel-and-viewer pair whose status is `ACTIVE` or `EXPIRED` — reversed timeouts do not count — and a channel short of that history is rejected with `ERR_PROGRESSIVE_DISCIPLINE`.

A viewer's `standing` is a derived, compound state recomputed on every action issuance, reversal, and expiry. With at least one `ACTIVE` `BAN`, the viewer is `BANNED`. Otherwise, with at least one `ACTIVE` `TIMEOUT`, the viewer is `TIMED_OUT`. Otherwise the viewer is `GOOD_STANDING`. The six arcs follow directly: `GOOD_STANDING` to `TIMED_OUT` when a timeout becomes active while no ban is active; `GOOD_STANDING` or `TIMED_OUT` to `BANNED` when a ban becomes active; `TIMED_OUT` back to `GOOD_STANDING` when the last active timeout is reversed or expires with no ban active; and `BANNED` to `GOOD_STANDING` or to `TIMED_OUT` when all active bans are reversed, landing on the latter when a timeout remains active. The ban is the punishing cascade: the moment a viewer becomes `BANNED`, every subscription of that viewer on the channel in `ACTIVE` or `PAST_DUE` moves to `CANCELLED`, and those subscriptions' grants in `PENDING` or `FAILED` move to `VOIDED` — exactly the cascade §3.4 attaches to owner cancellation.

Reversal is available to the owner and to an `AppealsOfficer`, with a `reason` recorded on the request; it moves an `ACTIVE` action to `REVERSED`, recomputes the viewer's standing, and decrements the issuing moderator's `actions_issued_count` by 1. Timeouts also die of old age: ops step 10 moves an `ACTIVE` `TIMEOUT` whose `expires_at` has been reached or passed to `EXPIRED` and recomputes standing. The action list accepts `channel_id`, `viewer_id`, `moderator_id`, and `action_status` filters.

### 3.6. Content Strikes, Appeals, and Trust Scoring

Platform compliance enters through the strike. A `TrustAgent` issues a strike with a `policy_code` — `COPYRIGHT`, `HATE_SPEECH`, `NUDITY`, `HARASSMENT`, or `SPAM` — a `severity` of `MINOR`, `MAJOR`, or `SEVERE` (carrying weight 1, 2, or 3 respectively), and an `evidence_ref` pointing at the supporting material. The strike is born `ISSUED`; `issued_at` is stamped from the clock; `expires_at` is set ninety days out, the hard-window decay boundary of §2.7; `appeal_deadline` is set fourteen days out; `appeal_round` starts at 0; and the issuer's `X-User-ID` is recorded as `issued_by_user_id` for the segregation-of-duties check below. Issuance immediately recomputes the channel's posture under §2.7 — including the payout-hold cascade when the weight crosses three. The strike list accepts a `strike_status` filter.

Appeals are the owner's recourse, and each strike allows exactly two rounds. From `ISSUED`, and again from `UPHELD`, the owner may appeal with a `statement` making their case. Two gates guard the move, checked in the §2.9 order: the clock must not have passed the strike's `appeal_deadline` (`ERR_APPEAL_WINDOW_CLOSED`), and `appeal_round` must still be below the cap of 2 (`ERR_APPEAL_LIMIT_REACHED`). A valid appeal moves the strike to `UNDER_APPEAL` and increments `appeal_round` by 1; the strike's weight still counts while the appeal is pending, so posture is recomputed but rarely changes on this arc.

Resolution belongs to an `AppealsOfficer`, never to the issuer: the resolver's `X-User-ID` must differ from the strike's `issued_by_user_id`, and a self-review is rejected with `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403). The resolution request carries an `outcome` — `UPHELD` or `REVERSED` — and a `resolution_note`. Upholding stamps `upheld_at`, recomputes `appeal_deadline` as fourteen days after `upheld_at` — opening the second and final appeal window — and recomputes posture. Reversing removes the strike's weight, recomputes posture, and, when the recomputation returns the channel to `STANDARD`, releases the channel's payouts held with `hold_reason` `POSTURE` back to `SCHEDULED`.

Strikes also decay on their own. An ops run expires any strike in `ISSUED` or `UPHELD` whose `expires_at` has been reached or passed, moving it to the terminal `EXPIRED`, removing its weight, and recomputing posture. A strike `UNDER_APPEAL` is exempt from expiry — the pending appeal tolls the ninety-day window — so an appeal in flight cannot be swept out from under its owner.

One number on the channel is deliberately decoupled from all of this. `projected_strike_weight` is an analytics-only projection: over the channel's strikes in `ISSUED`, `UNDER_APPEAL`, `UPHELD`, or `EXPIRED` status within the last 180 days, each strike contributes its severity weight multiplied by a continuous decay factor — one-half raised to the power of the strike's age in days divided by thirty, so a strike loses half its contribution every thirty days — and the contributions are summed and rounded half up to four decimal places. The projection therefore declines smoothly instead of falling off the ninety-day cliff, and it **never** gates posture; the canonical hard-window weight of §2.7 is the only weight that does.

### 3.7. Sponsorship Deals, Deliverables, and Disclosure Compliance

Sponsorship money is contract-shaped. The owner drafts a deal naming the sponsor through `sponsor_ref` — which must equal the sponsor's `X-User-ID` on every sponsor-privileged action — plus a `title`, a `category` of `GAMING_HARDWARE`, `ENERGY_DRINK`, `VPN`, `GAME_PUBLISHER`, or `OTHER`, the contracted `total_value_cents`, the campaign flight as the closed interval between `flight_start` and `flight_end`, and the `required_deliverable_count` of verified deliverables needed to complete the deal. A new deal is born `DRAFT` with `miss_count` 0 and `disclosure_compliant` true. The deal list accepts `deal_status` and `category` filters.

The negotiation arc is short. The owner proposes, moving the deal from `DRAFT` to `PROPOSED`; the sponsor accepts, moving it from `PROPOSED` to `ACCEPTED` — with the sponsor's `X-User-ID` checked against `sponsor_ref`, a mismatch drawing `ERR_SPONSOR_MISMATCH` — and the owner may cancel from any of `DRAFT`, `PROPOSED`, or `ACCEPTED`, moving the deal to the terminal `CANCELLED`.

Activation is the gatekeeper's moment, and three conditions guard the move from `ACCEPTED` to `ACTIVE`: the channel's posture must not be `SUSPENDED` (`ERR_CHANNEL_SUSPENDED`); the clock must fall within the closed flight interval — at or after `flight_start` and at or before `flight_end` (otherwise `ERR_INVALID_STATE`); and category exclusivity must hold, meaning no other deal of the channel in `ACCEPTED` or `ACTIVE` status with the same `category` may have a closed flight interval intersecting this one, where even a shared boundary instant counts as a conflict (`ERR_CATEGORY_EXCLUSIVITY_CONFLICT`). Activation books the revenue: a `SPONSORSHIP` revenue event is created with `gross_cents` equal to `total_value_cents`, a `platform_fee_bps` of 1,000 — a ten percent platform cut — `occurred_at` stamped from the clock, and `recognition_status` `PENDING`, so sponsorship money enters the ledger through the same recognition pipeline as every other kind.

Deliverables are the unit of performance, and they may be added only while the deal is `ACTIVE`. The owner adds one with a `kind` of `AD_READ`, `SPONSORED_SEGMENT`, `LOGO_PLACEMENT`, or `PRODUCT_PLACEMENT`, a `due_at` that must lie within the deal's flight, and optionally a `stream_id` naming the stream the deliverable will be performed in — null until the deliverable is scheduled against a stream, and the referenced stream must belong to the deal's channel (otherwise `ERR_NOT_FOUND`). A deliverable carries **two parallel state dimensions on one row**: `performance_status`, walking `SCHEDULED`, `PERFORMED`, `VERIFIED`, `MISSED`, and `DISPUTED`, and `disclosure_status`, walking `PENDING`, `DISCLOSED_ON_TIME`, `DISCLOSED_LATE`, and `MISSING`. A new deliverable starts `SCHEDULED` on the performance axis and `PENDING` on the disclosure axis, and the only terminal resting place is `VERIFIED` with any disclosure value other than `PENDING`. The deliverable list accepts `deal_id`, `stream_id`, `performance_status`, and `disclosure_status` filters.

Performance is the owner's move, requires a `stream_id` naming the stream the deliverable was performed in, and is guarded three ways: the channel must not be `SUSPENDED` (`ERR_CHANNEL_SUSPENDED`), the clock must not have passed `due_at` (`ERR_DELIVERABLE_OVERDUE`), and the referenced stream must have `stream_status` `ENDED` (`ERR_INVALID_STATE`). A valid performance moves the deliverable from `SCHEDULED` to `PERFORMED`, stamps `performed_at`, binds the stream, and sets `disclosure_deadline` to exactly twenty-four hours after `performed_at`.

Disclosure then runs on its own axis. The owner discloses a `PERFORMED` deliverable: within the deadline the axis moves from `PENDING` to `DISCLOSED_ON_TIME`; past the deadline it moves to `DISCLOSED_LATE`. Either way the deal's `disclosure_compliant` is recomputed — it is true exactly when no deliverable of the deal sits in `DISCLOSED_LATE` or `MISSING`, so a late disclosure flips it false. Silence is worse: when an ops run finds the clock more than seventy-two hours past `performed_at` with no disclosure recorded, the axis is forced to `MISSING`, again flipping `disclosure_compliant` false.

Verification belongs to the sponsor, whose `X-User-ID` must match `sponsor_ref` (`ERR_SPONSOR_MISMATCH`), and disclosure comes first: verification while the disclosure axis is `PENDING` or `MISSING` is rejected with `ERR_DISCLOSURE_REQUIRED`, so only `DISCLOSED_ON_TIME` or `DISCLOSED_LATE` deliverables can be verified. Verification moves the deliverable to `VERIFIED` — reachable from `PERFORMED` and, after a dispute, from `DISPUTED` — and the deal's `verified_deliverable_count` is recomputed. The sponsor may instead dispute a `PERFORMED` deliverable under the same identity rule, moving it to `DISPUTED`.

Missing a deadline has permanent consequences. Ops step 6 moves a deliverable still `SCHEDULED` past its `due_at` to `MISSED` and increments the deal's `miss_count` by 1. When the count reaches three, the deal is breached: it moves from `ACTIVE` to the terminal `BREACHED`, and the platform claws the sponsorship back by creating a `CHARGEBACK` revenue event whose `gross_cents` is the negation of `total_value_cents`, whose `platform_fee_bps` is 1,000, whose `reverses_event_id` names the activation-time `SPONSORSHIP` event, and whose `recognition_status` is `CLEARED` — the clawback net lands in the channel's `balance_payable_cents` immediately, per §3.2.

A miss or a dispute is not the end of the deliverable itself. The owner may reschedule one from `MISSED` or from `DISPUTED` back to `SCHEDULED`, supplying a new `due_at` within the deal flight plus the OCC field `expected_deliverable_version` of §2.8 — a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). Rescheduling replaces `due_at`, resets the disclosure axis to `PENDING`, and increments the deliverable's `version` by 1; rescheduling from `DISPUTED` additionally clears `performed_at` and unbinds `stream_id`. What rescheduling never does is decrement `miss_count` — misses are permanent history.

Completion is the quiet counterpart of breach, evaluated at ops step 9: an `ACTIVE` deal becomes the terminal `COMPLETED` when its `verified_deliverable_count` has reached `required_deliverable_count`, the clock has reached or passed `flight_end`, and `disclosure_compliant` is still true.

### 3.8. Stream Scheduling, Simulcast Rights, and Consistency Scoring

Streams are the channel's public heartbeat. The owner schedules one with a `title`, a `scheduled_start`, and a `scheduled_end` that must be strictly later, the pair forming a **half-open** interval that includes the start and excludes the end; the new stream is born `SCHEDULED`. Scheduling is exclusive within the channel: no other stream of the channel in `SCHEDULED` or `LIVE` status may have a half-open window intersecting the new one, though adjacency is expressly allowed — a new stream may begin at the exact instant a sibling ends. A violation is rejected with `ERR_STREAM_WINDOW_CONFLICT`. The optional `simulcast` flag defaults to false, and setting it true engages the rights machinery below at start time. The stream list accepts a `stream_status` filter.

Going live has a grace period. The owner starts a `SCHEDULED` stream, moving it to `LIVE`, and the clock must not be more than thirty minutes past `scheduled_start` — a start attempted after the grace window is rejected with `ERR_INVALID_STATE`, and a stream still `SCHEDULED` once the grace has elapsed is marked `NO_SHOW` by ops step 5. A simulcast start additionally requires an `APPROVED` simulcast grant for the channel whose closed window fully covers the scheduled window from `scheduled_start` through `scheduled_end`; without one the start is rejected with `ERR_SIMULCAST_GRANT_MISSING`. Starting stamps `actual_start` and computes `punctuality_minutes_late` — null until then — as the whole minutes by which `actual_start` followed `scheduled_start`, or zero when the stream started on time or early.

Ending a stream is also the owner's move and requires two audience figures, `peak_viewers` and `avg_viewers`, to be supplied; the stream moves from `LIVE` to the terminal `ENDED`, `actual_end` is stamped, and the channel's `consistency_score_bps` is recomputed. The owner may instead cancel a `SCHEDULED` stream, moving it to the terminal `CANCELLED` — the cancelled slot deliberately stays in the scheduled set for scoring purposes — and an ops-run `NO_SHOW` lands in the same terminal bucket; both recomputes refresh the score as well.

That score measures schedule discipline over a trailing twenty-eight-day window: every stream of the channel whose `scheduled_start` falls between twenty-eight days before the clock and the clock itself. The **scheduled count** covers the window's streams in `LIVE`, `ENDED`, `NO_SHOW`, or `CANCELLED` status; when there are none, the score is a vacuous perfect 10,000 basis points. Otherwise the attendance rate is the share of the scheduled count whose status is `ENDED`. Punctuality enters as a factor: the mean `punctuality_minutes_late` over the `ENDED` streams — zero when none ended — is divided by the thirty-minute tolerance, that quotient is subtracted from one, and the result is floored at zero. Duration enters the same way: over the `ENDED` streams, each stream's actual duration (`actual_end` minus `actual_start`) is divided by its scheduled duration (`scheduled_end` minus `scheduled_start`), the ratios are averaged — one when none ended — and the average is capped at one. The score is then ten thousand times the attendance rate times the weighted blend of the three components: a base weight of one-half, plus three-tenths of the punctuality factor, plus two-tenths of the duration factor. All means are computed in exact rational arithmetic and the final figure is rounded half up once, to integer basis points, clamped into the range from 0 to 10,000.

Simulcasting to a second platform requires rights. The owner requests a grant with a target `platform` — `TWITCH`, `YOUTUBE`, or `KICK`, a superset of the `home_platform` pair — and a closed rights window from `window_start` to `window_end`, the latter strictly after the former. The `exclusive` flag defaults to false and is recorded, but the conflict rule that matters is platform-and-window based, not flag based. A new request is born `REQUESTED`.

Approval belongs to a `PlatformAdmin` and is guarded twice: the channel's posture must not be `SUSPENDED` (`ERR_CHANNEL_SUSPENDED`), and the **buffer rule** must hold — for every other `APPROVED` grant on the same channel and platform, the two windows must be separated by at least twenty-four hours in both directions, meaning either the new `window_start` falls at least twenty-four hours after the other's `window_end`, or the other's `window_start` falls at least twenty-four hours after the new `window_end`; a violation is rejected with `ERR_SIMULCAST_BUFFER_CONFLICT`. Denial moves a `REQUESTED` grant to the terminal `DENIED`; revocation moves an `APPROVED` grant to the terminal `REVOKED`; and ops step 4 expires an `APPROVED` grant whose `window_end` has been reached or passed, moving it to `EXPIRED`. The grant list accepts `grant_status` and `platform` filters.

## 4. Endpoint Definitions

All endpoints live under `/api`. Endpoints that create a new resource — channel onboarding, tax-form submission, revenue ingestion, chargeback creation through reversal, payout opening, tier creation, viewer registration, subscription start, moderator invitation, moderation-action issuance, strike issuance, deal drafting, deliverable creation, stream scheduling, and simulcast-grant requests — respond with 201 and the created resource. All other successful operations — reads, list retrievals, settings patches, and every lifecycle transition — respond with 200. The table below is deliberately minimal: request payloads, response content, side effects, and the exact gating conditions of every write are specified in the §3 narratives cross-referenced by the description column, and the per-action role restrictions on transition endpoints follow the actor assignments given there.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/api/channels` | Onboard a new creator channel (platform-side) | PlatformAdmin |
| GET | `/api/channels/{channel_id}` | Read a channel including computed posture, balances, and scores | PlatformAdmin, Creator, Moderator, Sponsor, TrustAgent, AppealsOfficer |
| PATCH | `/api/channels/{channel_id}/payout-settings` | Update payout schedule and threshold; OCC-guarded | Creator |
| POST | `/api/channels/{channel_id}/tax-forms` | Submit a tax form; supersedes the channel's current form; OCC-guarded | Creator |
| GET | `/api/tax-forms/{tax_form_id}` | Read a tax form | PlatformAdmin, Creator, TrustAgent |
| GET | `/api/tax-forms` | List tax forms with filters | PlatformAdmin, Creator, TrustAgent |
| POST | `/api/tax-forms/{tax_form_id}/transition` | Verify or reject a submitted form (VERIFY, REJECT) | TrustAgent |
| POST | `/api/channels/{channel_id}/revenue-events` | Ingest a revenue event; CHARGEBACK requires `reverses_event_id` | PlatformAdmin |
| GET | `/api/revenue-events/{revenue_event_id}` | Read a revenue event | PlatformAdmin, Creator |
| GET | `/api/revenue-events` | List revenue events with filters | PlatformAdmin, Creator |
| POST | `/api/revenue-events/{revenue_event_id}/reverse` | Reverse a CLEARED non-CHARGEBACK event, creating its chargeback | PlatformAdmin |
| POST | `/api/channels/{id}/payouts` | Open a payout sweeping the eligible payable balance | Creator |
| GET | `/api/channels/{id}/payouts` | List payouts of a channel | PlatformAdmin, Creator |
| POST | `/api/payouts/{payout_id}/transition` | Payout lifecycle: PROCESS, SETTLE_SUCCESS, SETTLE_FAILURE (PlatformAdmin); RETRY, CANCEL (Creator owner) | PlatformAdmin, Creator |
| POST | `/api/channels/{id}/tiers` | Create a subscription tier | Creator |
| GET | `/api/tiers/{tier_id}` | Read a tier | PlatformAdmin, Creator, Moderator, Sponsor, TrustAgent, AppealsOfficer |
| GET | `/api/channels/{id}/tiers` | List tiers of a channel | PlatformAdmin, Creator, Moderator, Sponsor, TrustAgent, AppealsOfficer |
| POST | `/api/tiers/{tier_id}/transition` | Retire or reactivate a tier (RETIRE, REACTIVATE) | Creator |
| POST | `/api/channels/{id}/viewers` | Register a viewer identity under a channel | PlatformAdmin |
| GET | `/api/viewers/{viewer_id}` | Read a viewer | PlatformAdmin, Creator, Moderator, AppealsOfficer |
| GET | `/api/channels/{id}/viewers` | List viewers of a channel | PlatformAdmin, Creator, Moderator, AppealsOfficer |
| POST | `/api/channels/{channel_id}/subscriptions` | Start a subscription; creates the cycle-1 revenue event and MERCH perk grant | PlatformAdmin |
| GET | `/api/subscriptions/{subscription_id}` | Read a subscription | PlatformAdmin, Creator |
| GET | `/api/subscriptions` | List subscriptions with filters | PlatformAdmin, Creator |
| POST | `/api/subscriptions/{subscription_id}/transition` | Billing lifecycle: MARK_PAST_DUE, RECOVER (PlatformAdmin); CANCEL (Creator owner) | PlatformAdmin, Creator |
| GET | `/api/subscriptions/{id}/perk-grants` | List perk grants of a subscription | PlatformAdmin, Creator |
| POST | `/api/perk-grants/{perk_grant_id}/transition` | Fulfillment lifecycle: FULFILL, FAIL, RETRY, VOID | Creator |
| POST | `/api/channels/{id}/moderators` | Invite a moderator | Creator |
| GET | `/api/moderators/{moderator_id}` | Read a moderator | PlatformAdmin, Creator, Moderator |
| GET | `/api/channels/{id}/moderators` | List moderators of a channel | PlatformAdmin, Creator, Moderator |
| POST | `/api/moderators/{moderator_id}/transition` | Moderator lifecycle: ACCEPT (Moderator self); SUSPEND, REINSTATE, REMOVE (Creator owner) | Creator, Moderator |
| POST | `/api/channels/{channel_id}/moderation-actions` | Issue a TIMEOUT or BAN against a viewer | Creator, Moderator |
| GET | `/api/moderation-actions/{moderation_action_id}` | Read a moderation action | PlatformAdmin, Creator, Moderator, AppealsOfficer |
| GET | `/api/moderation-actions` | List moderation actions with filters | PlatformAdmin, Creator, Moderator, AppealsOfficer |
| POST | `/api/moderation-actions/{moderation_action_id}/reverse` | Reverse an active moderation action | Creator, AppealsOfficer |
| POST | `/api/channels/{id}/strikes` | Issue a content strike | TrustAgent |
| GET | `/api/channels/{id}/strikes` | List strikes of a channel | PlatformAdmin, Creator, TrustAgent, AppealsOfficer |
| POST | `/api/strikes/{strike_id}/appeal` | Appeal a strike (round 1 from ISSUED, round 2 from UPHELD) | Creator |
| POST | `/api/strikes/{strike_id}/resolve-appeal` | Resolve an appealed strike (UPHELD or REVERSED), segregated from the issuer | AppealsOfficer |
| POST | `/api/channels/{id}/deals` | Draft a sponsorship deal | Creator |
| GET | `/api/deals/{deal_id}` | Read a deal | PlatformAdmin, Creator, Sponsor |
| GET | `/api/channels/{id}/deals` | List deals of a channel | PlatformAdmin, Creator, Sponsor |
| POST | `/api/deals/{deal_id}/transition` | Deal lifecycle: PROPOSE, ACTIVATE, CANCEL (Creator owner); ACCEPT (Sponsor matching `sponsor_ref`) | Creator, Sponsor |
| POST | `/api/deals/{deal_id}/deliverables` | Add a deliverable to an ACTIVE deal | Creator |
| GET | `/api/deliverables/{deliverable_id}` | Read a deliverable | PlatformAdmin, Creator, Sponsor |
| GET | `/api/deliverables` | List deliverables with filters | PlatformAdmin, Creator, Sponsor |
| POST | `/api/deliverables/{deliverable_id}/transition` | Deliverable lifecycle: PERFORM, DISCLOSE (Creator owner); VERIFY, DISPUTE (Sponsor matching `sponsor_ref`) | Creator, Sponsor |
| POST | `/api/deliverables/{deliverable_id}/reschedule` | Reschedule a MISSED or DISPUTED deliverable; OCC-guarded | Creator |
| POST | `/api/channels/{id}/streams` | Schedule a stream (half-open window, adjacency allowed) | Creator |
| GET | `/api/streams/{stream_id}` | Read a stream | PlatformAdmin, Creator, Sponsor, Moderator |
| GET | `/api/channels/{id}/streams` | List streams of a channel | PlatformAdmin, Creator, Sponsor, Moderator |
| POST | `/api/streams/{stream_id}/transition` | Stream lifecycle: START, END, CANCEL; END requires `peak_viewers` and `avg_viewers` | Creator |
| POST | `/api/channels/{id}/simulcast-grants` | Request simulcast rights for a platform window | Creator |
| GET | `/api/channels/{id}/simulcast-grants` | List simulcast grants of a channel | PlatformAdmin, Creator |
| POST | `/api/simulcast-grants/{simulcast_grant_id}/transition` | Grant lifecycle: APPROVE (buffer rule), DENY, REVOKE | PlatformAdmin |
| POST | `/api/ops/run` | Advance the ops checkpoint through the ten pinned steps of §2.5 | PlatformAdmin |
| POST | `/api/_clock/set_current_utc` | Set the logical clock; startup default is exactly 2026-08-01T00:00:00Z | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for every error are specified in the §2 and §3 narratives where the guarded workflow lives; this catalogue is only the identifier-to-status map.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_CHANNEL_OWNERSHIP_MISMATCH` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CHANNEL_SUSPENDED` | 409 |
| `ERR_SELF_REVIEW_FORBIDDEN` | 403 |
| `ERR_PROGRESSIVE_DISCIPLINE` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_APPEAL_LIMIT_REACHED` | 409 |
| `ERR_STREAM_WINDOW_CONFLICT` | 409 |
| `ERR_SIMULCAST_BUFFER_CONFLICT` | 409 |
| `ERR_SIMULCAST_GRANT_MISSING` | 409 |
| `ERR_CATEGORY_EXCLUSIVITY_CONFLICT` | 409 |
| `ERR_DELIVERABLE_OVERDUE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TIER_CODE_IN_USE` | 409 |
| `ERR_SPONSOR_MISMATCH` | 403 |
| `ERR_MODERATOR_NOT_ACTIVE` | 409 |
| `ERR_MODERATOR_SCOPE_MISSING` | 403 |
| `ERR_PERK_INVENTORY_EXHAUSTED` | 409 |
| `ERR_DISCLOSURE_REQUIRED` | 409 |
| `ERR_VIEWER_BANNED` | 409 |
| `ERR_TAX_FORM_NOT_VERIFIED` | 402 |
| `ERR_BELOW_PAYOUT_THRESHOLD` | 422 |
| `ERR_NO_ELIGIBLE_REVENUE` | 422 |
| `ERR_RETRY_LIMIT_REACHED` | 409 |
| `ERR_PAYOUT_IN_FLIGHT` | 409 |
| `ERR_CHARGEABILITY_VIOLATION` | 409 |
