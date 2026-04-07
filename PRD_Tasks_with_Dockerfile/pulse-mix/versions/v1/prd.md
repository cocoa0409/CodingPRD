# PulseMix Studio

PulseMix is a backend for labels and creators who build **cycle-based** promotional playlists (“mixes”) while operating inside a rights, dispute, and budget policy environment.

PulseMix is built to let curators move quickly without letting a studio publish (or keep live) content in a way that violates rights or exceeds its per-cycle distribution budget. Legal corrections and disputes can change what is allowed underneath an in-flight plan, and the studio stays within policy anyway.


## What PulseMix includes

A single **Studio** owns four resources: **Assets** (audio items that can be used in mixes), **Clearances** (legal permission attached to exactly one asset), **Mixes** (playlists with a lifecycle from `DRAFT` through `PUBLISHED`), and **Disputes** (claims against an asset or a mix that can quarantine, freeze, or yank content).

Everything is studio-scoped. No sharing across studios.

Studios also carry a `name` that clients can display and use to distinguish one studio from another.


## Roles (required on every request)

We don't do user accounts yet; the client declares its role per request.

`curator` uploads and edits assets, authors mixes, and submits mixes. `manager` approves mixes and controls publishing and removal (publish, unpublish, archive). `legal` manages rights and enforcement: it grants, suspends, and revokes clearances, opens and resolves disputes, can publish evidence mixes, and can freeze mixes.

Role is passed via header: `X-Studio-Role`.


## Cycles

Studios operate in integer cycles. Cycle changes are explicit—no calendar logic.

Each studio has a monotone `cycle_index` that starts at `1`, and `POST /studios/:id/advance-cycle` increments it. Cycle changes draw a boundary for queued work and for what stays live.

Queued work is cycle-scoped—anything not published by the end of the cycle doesn't carry forward. Idempotency keys are also cycle-scoped and forgotten when the cycle advances.


## Studio posture

A studio has a posture that gates actions. In `OPEN`, the studio operates normally. In `REVIEW`, publishing is more restrictive. In `HALT`, the studio is in an emergency stop posture.

Posture is derived from disputes in the studio:

If any dispute is in `ESCALATED`, posture is `HALT`. Otherwise, if there are two or more disputes in `OPEN`, posture is `REVIEW`. Otherwise posture is `OPEN`.

Posture recalculates after every dispute create/resolve/void and after cycle advance.


## Token budget and accounting

Every studio has a per-cycle **token budget** that caps how much content can be queued or live at once.

At all times, the studio must not reserve and commit more tokens than it has budget for. The studio’s `token_reserved` plus its `token_committed` must never exceed `token_budget`.

`token_reserved` is the sum of `token_cost` for mixes that are queued (`SUBMITTED` or `APPROVED`). `token_committed` is the sum of `token_cost` for mixes that are live (`PUBLISHED` or `FROZEN`). `token_available` is whatever remains after accounting for reserved and committed tokens.

Evidence mixes never count toward tokens.

### How token cost works

A mix’s `token_cost` is derived from its entries and the **current** durations of its assets.

Each entry starts with a base cost determined by the referenced asset’s `duration_sec`: it costs `1` when `duration_sec` is `120` seconds or less, `2` when it’s from `121` to `240`, `3` when it’s from `241` to `420`, and `4` when it’s above `420`. The entry’s slot then adjusts that cost: `NORMAL` uses the base cost, while `SPOTLIGHT` adds one extra token on top.

The mix’s pre-discount token cost is the sum across all entries (duplicates count multiple times). The mix kind then applies its token rule: `PUBLIC` keeps the sum as-is; `INTERNAL` halves the sum and rounds down, but a non-empty internal mix always costs at least `1`; and `EVIDENCE` always costs `0`.

If an asset's duration is corrected, every referencing mix's token_cost may change. Studio token fields are derived from mix token_costs, so they update whenever token_cost or mix status changes.


## Budget enforcement vs. budget shedding

Client-initiated actions that would violate the token invariant fail. Submitting a mix, publishing a mix, or editing entries in a way that would push the studio over budget must be rejected.

Some actions represent legal truth and are not rejected for budget reasons: opening a dispute, resolving or voiding a dispute, suspending or revoking a clearance, and legal duration correction on an active/quarantined asset.

Those actions never fail due to budget. If they cause the studio to exceed `token_budget`, the system sheds load until the studio is back within budget by first bouncing queued mixes (status `SUBMITTED` or `APPROVED`) back to `DRAFT`, and only if that is not enough, archiving live mixes (status `PUBLISHED` or `FROZEN`).

Shedding order is strict: INTERNAL mixes first, then PUBLIC. Within the same kind, highest token_cost goes first. Ties break by lexicographically smaller mix id.


## Assets

Assets start as drafts and become usable only once activated.

Assets move through four statuses. `DRAFT` assets are editable by `curator`. `ACTIVE` assets are eligible for mixes (subject to clearance policy and disputes). `QUARANTINED` assets are not eligible for normal mixes and are typically dispute-driven. `RETIRED` assets are permanently unusable.

Curators can edit an asset’s title and duration only while the asset is `DRAFT`. Legal can perform a duration correction on `ACTIVE` or `QUARANTINED` assets (duration only); that correction forces the asset to be (or remain) `QUARANTINED` and suspends any granted clearance.

Activation is explicit: `POST /studios/:studio_id/assets/:asset_id/activate` attempts to move an asset from `DRAFT` to `ACTIVE`. It succeeds only when the asset is currently `DRAFT`, there is a clearance in `GRANTED` for the asset, the studio posture is not `HALT`, and there is no open or escalated dispute targeting the asset.

When an asset's status changes, any mixes that reference it reflect that immediately—queued mixes bounce back to draft, live mixes freeze or get archived depending on what changed.


## Clearances

Exactly one clearance may exist per asset.

Clearances are the legal permission record for an asset. Clients rely on three clearance fields: `policy` (`FULL` or `PROMO`), `status` (`PENDING`, `GRANTED`, `SUSPENDED`, `REVOKED`), and `last_granted_in_cycle` (the cycle index when it was last granted, or null if never granted).

Policy defines allowed use. Under `FULL`, an asset may be used in `PUBLIC` or `INTERNAL` mixes. Under `PROMO`, an asset may be used only in `INTERNAL` mixes and may never appear in a `SPOTLIGHT` slot.

Only `legal` can grant, suspend, or revoke a clearance. Granting is blocked while studio posture is `HALT`. `REVOKED` is final.

Clearances also have automatic effects. When an asset is quarantined due to a dispute, any clearance in `GRANTED` becomes `SUSPENDED`. Suspending a clearance bounces any queued mixes (`SUBMITTED`/`APPROVED`) that reference the asset back to `DRAFT`, and freezes any live mixes (`PUBLISHED`/`FROZEN`) that reference the asset into `FROZEN`. Revoking a clearance archives any live mixes containing the asset, bounces queued mixes containing the asset, and retires the asset if the revocation came from an upheld dispute (see disputes).


## Mixes

A mix is a playlist of entries. Each entry references an asset and a slot type.

Mixes come in three kinds. `PUBLIC` mixes are intended for distribution and have the strongest gating. `INTERNAL` mixes are internal previews with relaxed duplicate rules and discounted `token_cost`. `EVIDENCE` mixes are legal-only artifacts for disputes, with special rules and `token_cost = 0`.

Mixes move through six statuses. `DRAFT` mixes are editable. `SUBMITTED` mixes are queued and holding tokens. `APPROVED` mixes have manager approval and may or may not be live. `PUBLISHED` mixes are live. `FROZEN` mixes are live but locked due to legal hold (dispute, clearance suspension, or manual freeze). `ARCHIVED` mixes are dead, do not hold tokens, and are immutable.

### Entry rules

For `PUBLIC` and `INTERNAL` mixes, the entries list has between 1 and 25 entries. Spotlight usage is capped: `PUBLIC` mixes can have at most 3 `SPOTLIGHT` entries, and `INTERNAL` mixes can have at most 5. If studio posture is `REVIEW`, any non-evidence mix is capped at 1 `SPOTLIGHT` entry.

Duplicate policy depends on kind. In `PUBLIC`, each `asset_id` may appear at most once. In `INTERNAL`, duplicates are allowed, but adjacent duplicates are not.

Evidence mixes have tighter constraints. An evidence mix has between 1 and 10 entries, and it cannot contain any `SPOTLIGHT` entries at all. Every referenced asset must currently be `QUARANTINED` and must have an associated dispute that is `OPEN` or `ESCALATED`. Evidence mixes may include duplicates, but still may not have adjacent duplicates.

### Editing entries as a correction mechanism

`PUT /mixes/:id/entries` replaces the full entries list. It is allowed when a mix is `DRAFT`, `SUBMITTED`, or `APPROVED`. If entries are edited while a mix is `SUBMITTED` or `APPROVED`, the mix resets to `DRAFT` and releases any reserved tokens.

Edits are **not** allowed for `PUBLISHED` or `FROZEN` mixes (unpublish/archive first).

### Submit / approve / publish

Submit is a `curator` action. It requires the mix to be `DRAFT`, validates entry rules and asset/clearance/dispute rules, and reserves tokens (increasing `token_reserved` by the mix's `token_cost`). If submitting would exceed the token budget, the request fails. Submit is blocked when posture is `HALT`.

Approve is a `manager` action and requires the mix to be `SUBMITTED`. If studio posture is `HALT`, approval is blocked. In `REVIEW`, a manager can approve, but `PUBLIC` publishing will still be blocked (see publish rules).

Publish rules depend on kind. `PUBLIC` and `INTERNAL` publishing requires `manager` and the mix must be `APPROVED`. Publishing is cycle-sensitive: `approved_in_cycle` must equal the current `cycle_index` or the mix is stale. `PUBLIC` publish requires studio posture `OPEN`, while `INTERNAL` publish is allowed in `OPEN` or `REVIEW`. Evidence publishing is `legal`-only and is allowed even in `HALT`, moving directly from `DRAFT` to `FROZEN`.

Publishing moves the mix to live state and makes it part of `token_committed` until it is unpublished/archived/cycle-advanced.

When a mix becomes live, it records the cycle it went live via `published_in_cycle`.

### Unpublish, freeze, archive

Unpublish is allowed from `PUBLISHED` or `FROZEN`. A `manager` can unpublish at any time; `legal` can unpublish only when the mix is `FROZEN`. Unpublish releases committed tokens immediately. After unpublish, if `approved_in_cycle` is still current the mix returns to `APPROVED`; otherwise it returns to `DRAFT`.

Freeze is `legal`-only and moves a mix from `PUBLISHED` to `FROZEN` while keeping tokens committed.

Archive is allowed from any status except already archived. Archiving releases whatever tokens the mix was holding (reserved or committed), and archived mixes are immutable.

### Cycle boundary behavior for mixes

On `advance-cycle`, queued mixes are cleared and live mixes are ended. Any `SUBMITTED` or `APPROVED` mix resets to `DRAFT` and releases reserved tokens. Any `PUBLISHED` or `FROZEN` mix becomes `ARCHIVED` and releases committed tokens. `DRAFT` stays `DRAFT`, and `ARCHIVED` stays `ARCHIVED`.

Cycle advance flushes the queue—SUBMITTED and APPROVED mixes reset to DRAFT—and ends the live set—PUBLISHED and FROZEN mixes become ARCHIVED.


## Disputes

A dispute targets either an asset or a mix.

Disputes name their target using `target_type` (`ASSET` or `MIX`) and `target_id`.

Disputes have `severity` (`LOW` or `HIGH`), `status` (`OPEN`, `ESCALATED`, `RESOLVED`, `VOID`), and a `resolution` of `UPHELD`, `DISMISSED`, or `VOID` (set when the dispute is no longer open).

Creation behavior:

`LOW` disputes are created as `OPEN`. `HIGH` disputes are created as `ESCALATED`.

Automatic effects when a dispute is created:

If a dispute targets an asset, the asset becomes `QUARANTINED` (unless it is already `RETIRED`), and any clearance in `GRANTED` becomes `SUSPENDED`. Mixes that reference the asset are then adjusted: any queued mix (`SUBMITTED` or `APPROVED`) bounces to `DRAFT` and releases reserved tokens; any `PUBLISHED` mix becomes `FROZEN` for a `LOW` dispute and becomes `ARCHIVED` (releasing committed tokens) for a `HIGH` dispute.

If a dispute targets a mix, a `SUBMITTED` or `APPROVED` mix bounces to `DRAFT`. If the mix is `PUBLISHED`, a `LOW` dispute freezes it into `FROZEN`, while a `HIGH` dispute archives it into `ARCHIVED`.

Resolution behavior (legal only):

Resolution is `legal`-only. When a dispute is resolved as `DISMISSED`, the dispute becomes `RESOLVED`, posture recalculates, and quarantine is removed only if no other open/escalated disputes remain on that target. Rights are not automatically restored: suspended clearances remain suspended until `legal` explicitly grants again.

When a dispute is resolved as `UPHELD`, the dispute becomes `RESOLVED`. If the dispute targeted an asset, the asset becomes `RETIRED`, its clearance becomes `REVOKED`, and any mixes containing it become `ARCHIVED`. If the dispute targeted a mix, that mix becomes `ARCHIVED`.

When a dispute is marked `VOID`, the dispute becomes `VOID`, posture recalculates, and quarantine is removed only if no other open/escalated disputes remain. Clearances stay as-is (no auto-regrant).

Resolving or voiding a dispute never automatically re-grants a suspended clearance. Legal must explicitly grant again if they want to restore rights.


## Idempotency, versions, and effects

### Idempotency (POST only)

Every POST requires `Idempotency-Key`.

An idempotency key is scoped to `(studio_id, cycle_index, method, path)`. Replaying the same request returns the exact same stored response. Reusing the same key with a different request body returns `ERR_IDEMPOTENCY_REPLAY_MISMATCH`. Advancing the cycle clears all remembered keys.

### Optimistic concurrency (If-Match)

Every resource carries an integer `version`. `PATCH` and `PUT` require `If-Match` (exact version) or fail with `ERR_MISSING_IF_MATCH` or `ERR_VERSION_CONFLICT`. For POST action endpoints on existing resources, `If-Match` is optional; if provided and wrong, the request fails with `ERR_VERSION_CONFLICT`.

### Effects

Because many actions cascade, success responses include an `effects` array describing other resources that changed as a side effect. Each effect names the resource by `type` (`studio`, `asset`, `clearance`, `mix`, `dispute`) and `id`, and carries the resource's new `status` (when it has one) and `version`. For studios, effects also include the updated token fields, posture, and `cycle_index` (plus `version`). For mixes, effects also include the updated `token_cost` when it changed.

### Success response format

Success responses return the primary resource fields directly at the response root, alongside the `effects` array. For example, creating a studio returns something like:

```
{ "id": "…", "name": "…", "posture": "OPEN", "cycle_index": 1, …, "effects": [] }
```

GET endpoints return the resource the same way (fields at root, no wrapper).


## Error handling and precedence

All errors return:

```

{ "error": { "code": "ERR_*", "message": "…" } }

```

Precedence when multiple failures are possible (highest wins):
First `ERR_NOT_FOUND`. Next `ERR_MISSING_IDEMPOTENCY_KEY` (POST) or `ERR_MISSING_IF_MATCH` (PUT/PATCH). Next `ERR_IDEMPOTENCY_REPLAY_MISMATCH` or `ERR_VERSION_CONFLICT`. Next `ERR_ROLE_FORBIDDEN`, then `ERR_POSTURE_BLOCKED`, then `ERR_INVALID_STATE`. After that come entry/relationship policy errors (duplicates, spotlight, clearance, dispute blocking, cycle stale). Finally, `ERR_TOKEN_BUDGET_EXCEEDED`.

Within “entry/relationship policy errors”, precedence is:

`ERR_DISPUTE_BLOCKING` > `ERR_ASSET_NOT_ACTIVE/ERR_ASSET_QUARANTINED` > clearance errors > entry-shape errors.

### Required headers

- `Content-Type: application/json`
- `X-Studio-Role: curator | manager | legal`
- `Idempotency-Key: <string>` (required for all POST)
- `If-Match: <int>` (required for PUT/PATCH; optional on POST actions)

### Endpoints

POST /studios  
GET /studios/:studio_id  
POST /studios/:studio_id/advance-cycle

POST /studios/:studio_id/assets  
GET /studios/:studio_id/assets/:asset_id  
PATCH /studios/:studio_id/assets/:asset_id  
POST /studios/:studio_id/assets/:asset_id/activate

POST /studios/:studio_id/clearances  
POST /studios/:studio_id/clearances/:clearance_id/grant  
POST /studios/:studio_id/clearances/:clearance_id/suspend  
POST /studios/:studio_id/clearances/:clearance_id/revoke

POST /studios/:studio_id/mixes  
GET /studios/:studio_id/mixes/:mix_id  
PUT /studios/:studio_id/mixes/:mix_id/entries  
POST /studios/:studio_id/mixes/:mix_id/submit  
POST /studios/:studio_id/mixes/:mix_id/approve  
POST /studios/:studio_id/mixes/:mix_id/publish  
POST /studios/:studio_id/mixes/:mix_id/unpublish  
POST /studios/:studio_id/mixes/:mix_id/freeze  
POST /studios/:studio_id/mixes/:mix_id/archive

POST /studios/:studio_id/disputes  
POST /studios/:studio_id/disputes/:dispute_id/resolve

Errors
- error.code is one of:
  - ERR_BAD_REQUEST
  - ERR_NOT_FOUND
  - ERR_MISSING_IDEMPOTENCY_KEY
  - ERR_MISSING_IF_MATCH
  - ERR_IDEMPOTENCY_REPLAY_MISMATCH
  - ERR_VERSION_CONFLICT
  - ERR_ROLE_FORBIDDEN
  - ERR_POSTURE_BLOCKED
  - ERR_INVALID_STATE
  - ERR_CYCLE_STALE
  - ERR_TOKEN_BUDGET_EXCEEDED
  - ERR_ENTRY_LIMIT
  - ERR_ENTRY_DUPLICATE_PUBLIC
  - ERR_ENTRY_ADJACENT_DUPLICATE
  - ERR_SPOTLIGHT_NOT_ALLOWED
  - ERR_SPOTLIGHT_CAP_EXCEEDED
  - ERR_ASSET_NOT_ACTIVE
  - ERR_ASSET_QUARANTINED
  - ERR_CLEARANCE_REQUIRED
  - ERR_CLEARANCE_SUSPENDED
  - ERR_CLEARANCE_POLICY_MISMATCH
  - ERR_DISPUTE_BLOCKING
  - ERR_CLEARANCE_ALREADY_EXISTS