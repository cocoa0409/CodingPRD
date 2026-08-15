# Worklog — task_1978_free_ad_supported_tv_channel_operations

## Step 1: Create Task Directory — 2026-08-15T04:20:00.000Z

Pre-done by the invoking pipeline: `tasks/task_1978_free_ad_supported_tv_channel_operations/` and `workspace/` already existed. Orchestrator did not scan or create any other task_* directory.

## Step 2: Generate Scaffold — 2026-08-15T05:19:00.000Z

All three files are written, lint-clean, and verified on disk.

## Summary — task_1978_free_ad_supported_tv_channel_operations

**Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1978_free_ad_supported_tv_channel_operations/`):**
- `SCAFFOLD.yaml` — 1,929 lines, 103 KB (§1.0–§1.7 only; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 810 lines, 83 KB (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1,616 lines, 158 KB (single top key `scaffold_corner_design`)

**SCAFFOLD.yaml contents:**
- **Entities: 15** — Channel (dual state dimensions: `channel_status` × derived `channel_posture`), ContentAsset, RightsGrant, PlaylistLoop (self-referential `supersedes_loop_id`), PlaylistEntry, AdBreak, FillDecision, AdCampaign, AdCreative, HouseAd, DistributorPlatform, DistributionAgreement, RevenueReport, ViewershipEvent (append-only, `common_fields: false`, batched `quantity`), ChannelDaySnapshot
- **State machines: 13** — incl. parallel-dimension Channel, cyclic RevenueReport dispute/refinalize loop (bounded at 3 rounds), cyclic AdCampaign ACTIVE⇄PAUSED with auto EXHAUSTED⇄ACTIVE, cyclic AdCreative review loop, AdBreak DECIDED⇄MARKED
- **Concurrency rules: 3** (all OCC, 412): `loop-publish-stale-channel`, `decision-run-stale-break`, `report-recompute-stale-report`
- **Calculations: 14** — incl. dual-variant fill rate (direct vs effective) and revenue statement (provisional vs final), per-(decision,platform) rounding pinned vs sum-then-round, tiered marginal rev-share with pinned evaluation order, weighted performance score, chronological peak-concurrency replay, selector with full eligibility/ranking/tie-break/empty-pool pins, half-open vs closed interval overlap, exact-second loop tiling, strict-> refresh staleness
- **Validations: 13** priority tiers (auth → shape → role → existence → ownership → segregation → state → OCC → referential → safety → temporal → constraint → fiscal)
- **Endpoints: 87** (incl. `POST /v1/_clock/set-current-utc` with the mandated `2026-08-01T00:00:00Z` default; all server timestamps read the logical clock, making tie-breaks deterministic)
- **Errors: 35** — **Roles: 8** (7 opaque + `DistributorPartner` entity-backed by DistributorPlatform; segregation-of-duties on creative approval and report finalize/settle)

**§1.8 difficulty design: 19 instances** (rules 1–9 all ≥2; rule 2 has 3 covering modes a/b/c), every one with fully-structured `setup_api_calls`/`trigger` chains, literal-pinned arithmetic (e.g. fill rates 0.3333/0.6667, revenue 330→250, share 700 marginal split, scores 40/60).

**§1.9 corner design: 85 instances** (72 active + 13 `excluded_because` stubs) across all nine guide sections.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (87 endpoints, 15 entities, 19+72 instances, 986 calls scanned). Instance names unique across both design files (104/104); no forbidden race vocabulary present.

(Note: first scaffold subagent spawn exited mid-planning without writing files; a fresh subagent completed the generation above.)

## Step 3: Copy Shared Files — 2026-08-15T05:20:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1978_free_ad_supported_tv_channel_operations/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-15T05:40:00.000Z

PRD generation complete. The file exists at `/home/ubuntu/github/CodingPRD/tasks/task_1978_free_ad_supported_tv_channel_operations/workspace/PRD.md` (386 lines, 65,645 bytes). The one "MISS" in my spot-check was a checker-string artifact — the rule is present verbatim at line 192 ("must not exceed `max_plays`, with equality permitted").

## Summary

**Sections:**
1. Introduction (2 paragraphs, business-context angle)
2. Global Specifications — §2.1 RBAC (all 8 roles with identity prose: 7 opaque + `DistributorPartner` entity-backed to `DistributorPlatform`), §2.2 Response Structure (verified byte-identical to the fixed verbatim block), §2.3 Pagination, §2.4 Logical Clock, §2.5 Common Resource Properties (incl. `ViewershipEvent` carrying only `id`/`created_at`), §2.6 Dual Channel State Dimensions, §2.7 Monetary Precision/Basis Points, §2.8 OCC (all 3 rules), §2.9 Nested Retrieval, §2.10 Validation Priority Order (13 tiers as explicit ordered narrative)
3. Business Logic — 8 subsections (channel ops / content+rights / loop construction+offset walk / validate-lock-publish / trafficking / decision-run selector / air+reconcile+measurement / distribution+settlement)
4. Endpoint Definitions — 87 endpoints, 4-column table
5. Error Code Catalogue — 35 errors, 2-column table

**Coverage counts:**
- Field names: 126/126 present in backticks (15 entities' fields + all request-body, query-param, and path-param identifiers, including path-only `grant_id`, `entry_id`, `report_id`, `event_id`, `snapshot_id`)
- Errors: 35/35 in §5 table, 35/35 also mentioned in §2/§3 narrative
- Endpoints: 87/87 in §4 table; 14 calculations, 13 state machines, 3 OCC rules, 13 validation priority tiers all expressed in prose

**Hard contract reports:**
```
Field coverage check: 126 required, 126 present, 0 missing — PASS
  (entities fields / request_body / query_params / path_params all covered)
Rule coverage check: validations priority 13/13 ordered in prose; OCC 3/3
  (endpoint + expected_*_version + error_id + 412 named); transitions 13/13
  machines fully expressed; calculations 14/14 in reconstructible prose;
  side effects and applies_to scopes expressed; sibling branches symmetric — PASS
Path purity check (§3): 651 backtick tokens scanned; 0 start with `/`;
  0 bare HTTP methods; 0 method+path — PASS
```

**Judgment calls made:**
- `ERR_CHANNEL_POSTURE_FROZEN` pinned exactly to the four operations the scaffold names (loop validate/lock/publish, decision-runs); the `SUSPENDED → LIVE` resume block while FROZEN is stated without inventing an error id the scaffold doesn't declare.
- HTTP statuses in §5 follow the error catalog (e.g., `ERR_GRANT_WINDOW_OVERLAP`/`ERR_AGREEMENT_WINDOW_OVERLAP`/`ERR_DISPUTE_ROUND_LIMIT` at their catalog statuses), not the coarser per-tier statuses in the validations table.
- LOCKED-loop content-pull cascade: stated that committed decisions voided by a loop revert refund `committed_cost_cents` (per the FillDecision `VOIDED` transition listing "loop revert" as a trigger with the COMMITTED-only refund side effect).
- The §4 preamble states the 201/200/204 status-code rules; request/response bodies deliberately excluded from the table per the minimal-table contract.

## Step 5: Generate Unit Tests — 2026-08-15T06:05:00.000Z

All infrastructure and tests are written and verified. Final summary:

## Output

**test_helpers/ (9 files)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1978_free_ad_supported_tv_channel_operations/test_helpers/`:
- `types.py` — 15 entity TypedDicts (ViewershipEvent correctly omits `updated_at`/`version` per append-only semantics) + 17 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~65 methods incl. PATCH status endpoints and the logical-clock endpoint)
- `api_errors.py` — all 35 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (UUID/timestamp/enum/fill-accounting invariants)
- `factories.py` — payload factories, input fields only
- `constants.py` — PRD thresholds (SLOT_SECONDS 30, 25% ad capacity, MAX_DISPUTE_ROUNDS 3, 60000 watch / 2000 ecpm bonus thresholds, clock start, scenario dates)
- `test_users.py` — shared headers for the 7 opaque roles + `make_distributor_partner_headers(platform_id)` for the entity-backed role
- `fixtures.py` — composite fixtures: validated/locked/published loop chains, active campaign+creative, revenue-report scenario engine, exhausted-campaign setup, two-day score scenario, elapsed/provisional/finalized report chains
- `__init__.py` — barrel export

**test_suite/ (11 files)**: `conftest.py` + `test_01`…`test_10` — **111 tests**, every docstring ending with exactly one verbatim `Design:` line.

## Coverage
- **Queue A (Difficulty): 19/19 instances, each with exactly 2 tests (38 tests).**
- **Queue B (Corner): 72/72 non-stub instances emitted (73 tests — `agreement_activation_pins_rate_snapshot` split into pin + no-re-pin tests). 13 `excluded_because` stubs not translated**; all stub cross-refs resolve except one: `Corner/rbac/partner_can_dispute_own_finalized_report` → `r3_report_dispute_refinalize_cycle` (actual name `r3_report_dispute_refinalize_cycle_bounded`) — broken pointer, stub skipped per spec.

## Verification
- `py_compile` clean on all 20 files; all test modules import successfully with the framework on PYTHONPATH; no missing names against `test_helpers`.
- Tag audit: 111/111 tests tagged, all tags resolve to real instances, no stub translated, no `skip`/`xfail` markers.
- Citation audit: 142 long quoted PRD passages, all survive a whitespace-normalized literal grep of PRD.md (0 failures).

## PRD-first adjudications (repairs / scope reductions, claims never weakened to generic checks)
1. **r1 fill-rate instance**: chain had content 540s + 90s break = 630 > 600 (would fail `ERR_LOOP_OVERFLOW` at mark time) → repaired content to 510s; all asserted values (capacity 90, rates 0.3333/0.6667, costs 500/0) unchanged.
2. **Corner `publish_rejected_when_plays_exhausted_*`**: original numbers (max_plays 1) trigger the WINDOW_EXPIRED loop-revert cascade that reverts loop B to DRAFT before its publish, making `ERR_PLAYS_EXHAUSTED` unreachable → repaired to max_plays 3 with two 240s entries per loop (first publish consumes 2, second needs 2 with 1 left) — same asserted error and LOCKED-unchanged outcome.
3. **Corner `competitive_separation_within_window_*`**: with 30s creatives the first break's run would also place the IAB-7 creative on slot 1, excluding both categories from b2 → creatives set to 60s (spans whole break); asserted placements and offsets (120/780, gap 600 ≤ window 600) unchanged.
4. **Corner `house_ad_waterfall_follows_priority_weight`**: PRD's house waterfall has no within-break dedup, so slot 1 would take the weight-9 ad again (cap 5) → asserted only the PRD-derivable claims (slot 0 == weight-9 ad, both rows HOUSE, house_seconds 60, slate 0); dropped the slot-1 claim.
5. **Corner channel defaults / client-id instances**: dropped the `version == 1` sub-assertion (PRD never pins the initial version value, only that it increments).
6. **Corner `frozen_channel_blocks_loop_create`**: PRD §2.6 enumerates FROZEN-blocked operations (validate/lock/publish, decision runs, resume) and loop *create* is not among them → emitted the PRD-covered half (grant revoke under a PUBLISHED loop ⇒ posture FROZEN), omitted the create-rejection.
7. **r5 publish pair**: intra-tier-7 ambiguity between `ERR_INVALID_STATE_TRANSITION` (loop DRAFT) and `ERR_CHANNEL_NOT_LIVE` (channel DRAFT) → used `validate_error_is_one_of([...])` plus asserted the tier-11 temporal error never surfaces and HTTP 409 — preserving the instance's cross-tier claim.

## Step 6: Generate Implementation — 2026-08-15T06:05:00.000Z

All 87 scaffold endpoints are registered (the 88th route is Flask's built-in `/static` handler). The implementation is complete and verified.

## Summary

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_1978_free_ad_supported_tv_channel_operations/workspace/implementation/`

**File tree (18 files, 3810 lines):**
- `start.sh` (10) — guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`
- `requirements.txt` (1) — flask>=3.0,<4.0
- `app.py` (70) — app factory, ApiError/404/405 handlers producing the envelope, route registration
- `db.py` (75) — in-memory dict store (starts empty, zero seeding), logical clock defaulting to exactly 2026-08-01T00:00:00Z, `fmt_dt` (ISO-8601 UTC, 3 fractional digits), `touch` (updated_at + version)
- `errors.py` (52) — all 34 catalog error IDs with exact HTTP statuses
- `response.py` (101) — exact envelope (`meta.api_request_id` (`req_…`), `api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, clamp 1..100, offset floor 0), created_at-ascending sort
- `middleware.py` (59) — `X-User-ID`/`X-User-Role` auth, 8 roles
- `util.py` (139) — strict date/month/datetime parsing, Decimal ROUND_HALF_UP helpers
- `serializers.py` (184) — exact public field sets per entity
- `services/core.py` (337) — offset walk, rights coverage, posture recompute, fill accounting, void/exhaust/revive cascades, loop-revert cascade, content re-evaluation
- `services/selector.py` (378) — decision-run waterfall selector, revenue attribution/statement, snapshot computation
- `routes/`: channels.py (221), content.py (283), loops.py (509), decisions.py (176), campaigns.py (334), house_ads.py (103), platforms.py (273), reports.py (269), events.py (148), snapshots.py (88)

**Endpoints:** all 87 from the scaffold endpoint table.

**State machines:** all 12 (Channel lifecycle + derived posture with OFFLINE/ARCHIVED hold, ContentAsset, RightsGrant, PlaylistLoop, AdBreak, FillDecision, AdCampaign, AdCreative, HouseAd, DistributorPlatform, DistributionAgreement, RevenueReport).

**Calculations:** loop_offset_walk, loop_tiling_check (exact + 25% floor), rights_play_consumption, decision_slot_allocation (DIRECT ranking cpm→priority→created_at; HOUSE waterfall; competitive-separation gap with touching-counts; daily/total fiscal gates), committed/reconciled cost, cpm_revenue_attribution (per-(decision,platform) round-then-sum), revenue_share_statement (pinned 5-step order, marginal tiers, single statement-level rounding, minimum guarantee), fill rates (scale-4, 0.0000 on zero capacity), channel_performance_score, peak_concurrent_viewers (floor-0 replay), ecpm (pinned zero rule), posture recompute, refresh staleness (strict >).

**Validations:** full 13-tier priority order (headers → shape → role → existence (path left-to-right 404 / body FK 422) → ownership → segregation → state guards (incl. ERR_CHANNEL_NOT_LIVE, ERR_CHANNEL_POSTURE_FROZEN) → OCC (3 stale-version errors, 412) → referential usability → rights/ad-quality → temporal → uniqueness/capacity → fiscal).

**Key design decisions:** FROZEN coverage counts ACTIVE-or-EXHAUSTED grants (literal ACTIVE-only would deadlock every happy-path publish that exhausts a grant, contradicting the publish "clears GUARDED" semantics); the offset walk never bumps versions (OCC stability); a decision run bumps break version exactly once and never collapses DECIDED→MARKED (collapse is void-cascade-only per spec); run-ops expires grants globally and recomputes posture for affected channels.

**start.sh boot contract:** `bash start.sh` from `implementation/` → binds `0.0.0.0:$PORT` (default 10000), foreground via `exec`, HTTP-ready in ~1s (limit 60s), empty store + clock at 2026-08-01T00:00:00Z on every boot. Verified via fresh-boot probes plus 4 smoke suites (~150 assertions, all passing) covering CRUD, cascades, OCC, separation, budgets, exhaustion/revival, supersede, reports (provisional/final variants, disputes, segregation), snapshots, and pagination.

## Step 7: Run Tests and Iterate — 2026-08-15T06:20:00.000Z

Summary:

- **Iterations run:** 2 (first sweep: 2 deterministic failures in all 8 rounds; second sweep after fixes: all 8 rounds clean, 111/111 × 8).

- **Tests deleted (PRD-silence / unique-derivability):**
  - None deleted wholesale. One assertion excised per STEP 1c partial-coverage handling: `test_01_response_envelope_and_listing.py::test_list_pagination_defaults_and_bounds` — removed the `limit=0 → ERR_INVALID_REQUEST` assertion. PRD §2.3 says only "bounded below by 1 and above by 100" and §2.10 tier 2 scopes "numeric ranges respected" to request *body* shape; `limit` is a query parameter, so a faithful PRD-only reader could clamp (as the implementation does) or reject — the reject outcome is not uniquely derivable. All other assertions in the test (default 10, `limit`/`offset`/`total_count`/`has_more` fields, page arithmetic) are verbatim PRD-covered and were kept. (Scaffold rule that drove the assertion: a numeric-range validation the scaffold pinned to query-param bounds; PRD prose never named the rejection semantics for query params — Zero-Silence gap.)

- **Fixes applied to `test_helpers/`:** none — fixtures and factories were faithful to PRD.

- **Fixes applied to `test_suite/` (test bug, STEP 2):**
  - `test_03_content_rights_grants.py::test_publish_rejected_when_plays_exhausted_between_validate_and_publish` — removed a stray `tile_loop(loop["id"], ..., ())` call in the setup that appended a **third** 240s entry (240+240+240+120 = 840 > 600 loop duration), causing the PRD-faithful implementation to correctly reject setup with `ERR_LOOP_OVERFLOW`. With the call removed, each loop tiles exactly (2×240 + 120 = 600), the first publish consumes 2 of 3 plays, and the second publish (needing 2 with 1 left) surfaces the asserted `ERR_PLAYS_EXHAUSTED` with the loop staying `LOCKED` — matching the documented design intent and the PRD §3.4 plays rule verbatim.

- **Fixes applied to `implementation/`:** none required — the implementation was already PRD-faithful on every exercised rule; both failures traced to the test artifact layer.

- **Flakiness note:** the first sweep's console showed inline `FAILED` fragments for `test_loop_create_starts_in_draft` and `test_list_filter_by_campaign_status`; these were interleaving artifacts of 8 concurrent pytest processes sharing one output file (nodeid fragments glued to verdict fragments). The JUnit-derived `results.json` files and all 8 pytest summaries agreed exactly (2 failed / 109 passed per round), and the second sweep confirmed no real flakiness.

## Step 8: Finalize PRD — 2026-08-15T06:30:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1978_free_ad_supported_tv_channel_operations/workspace/PRD_FINALIZED.md` written with a single in-place revision.

**Line counts / %-delta**
- PRD.md: 386 lines; PRD_FINALIZED.md: 386 lines; 0% line-count delta (one line revised in place, +~280 chars on that line).

**Changes**
- §2.3 Pagination — revise — pinned that an out-of-range `limit` query value is clamped to the nearest bound (so `limit=0`→1, `limit=500`→100) rather than rejected with an error, and that the clamped value is the effective limit used to slice the page and echoed in the response `meta` — `implementation/response.py:82` (clamp), `response.py:45` (meta echo), `response.py:100` (page slice).

**Step 7 items requiring no PRD edit**
- `test_03_content_rights_grants.py` tile_loop fix — pure test-artifact bug (an extra 240s entry made setup correctly fail with `ERR_LOOP_OVERFLOW`); implementation unchanged and PRD §3.4 plays rule already matched verbatim. Nothing to pin.

**Per-edit pre-edit search log**
- Edit 1 (§2.3 limit clamping):
  - (a) Subject: handling of the `limit` pagination query parameter (default, bounds, out-of-range semantics, meta echo).
  - (b) Impl paths enumerated: `grep -rn "limit"` and `grep -rn "request.args"` across all `implementation/**.py`. `limit`/`offset` are read in exactly one place — `parse_pagination()` at `implementation/response.py:70-91` (default 10; clamp `max(1, min(100, limit))` at line 82; non-integer rejected with `ERR_INVALID_REQUEST` at line 81; offset floored at 0, line 90). `paginate()` (response.py:94-101) is the sole consumer, and every list endpoint routes through it: `routes/content.py:74,224`, `routes/snapshots.py:81`, `routes/loops.py:136,193,285`, `routes/platforms.py:81,205`, `routes/house_ads.py:77`, `routes/channels.py:95`, `routes/events.py:140`, `routes/reports.py:153`, `routes/campaigns.py:104,238`, `routes/decisions.py:154`. All other `request.args` reads are unrelated filter params. Also grepped PRD for pre-existing "clamp/bounded/out of range" wording (only §2.3 line 83 and an unrelated `after_entry_index` clamp at line 174) to avoid contradiction.
  - (c) Wording adjustment: because the single shared helper clamps both ends for all 15 list endpoints, the wording was written to cover both bounds ("clamped to the nearest bound") rather than only the `limit=0` lower-bound case from the excised assertion, and scoped strictly to out-of-range integers ("a supplied value outside that range") so it cannot be read as suppressing the non-integer `ERR_INVALID_REQUEST` rejection at response.py:81. `offset` wording left untouched (PRD already silent; no Step 7 item covered it — under-determination preferred over a new claim).

## Step 9: Complete PRD — 2026-08-15T07:00:00.000Z

All 28 paragraph-level edits verified in place. The task is complete. Here is the summary.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1978_free_ad_supported_tv_channel_operations/workspace/PRD_COMPLETED.md`

**Source vs output:** PRD_FINALIZED.md 386 lines / 65,916 chars → PRD_COMPLETED.md 386 lines / 71,237 chars (**+5,321 chars, +0 lines** — all edits are inline in-paragraph inserts/revisions; no new sections, no new paragraphs).

**Counts:** 36 logical changes = **32 ambiguity-pins** + **4 mismatch-revisions**.

### Changes

- **§2.3** — insert — ambiguity — negative `offset` clamps to 0; non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` — `implementation/response.py:70-91`
- **§2.3** — insert — ambiguity — list sort ties on `created_at` broken by creation (insertion) order — `implementation/response.py:94-101`
- **§2.5** — insert — ambiguity — `version` starts at 1 at creation — `implementation/db.py` `_create_record` (e.g. `routes/channels.py:24-34`), `db.py:72-75`
- **§2.6** — revise — **mismatch** — FROZEN rule counts grants in `ACTIVE` **or `EXHAUSTED`** status as covering (PRD said only "active"); PENDING/REVOKED/EXPIRED never count — `implementation/services/core.py:124-143`
- **§2.6** — insert — ambiguity — enumerates the offline/archived prohibition (entry/break add/remove, validate, revert, lock, unlock, decision runs → `ERR_INVALID_STATE_TRANSITION`; frozen check fires first on validate/lock/decision-run), and states loop creation, loop archival, mark-aired, reconcile are not channel-status-restricted — `implementation/services/core.py:324-337`, `routes/loops.py:86-117,497-509`, `routes/decisions.py:75-129`
- **§2.8** — insert — ambiguity — absent/non-integer expected-version field → `ERR_INVALID_REQUEST` before comparison — `routes/loops.py:439-441`, `routes/decisions.py:40-42`, `routes/reports.py:185-187`
- **§3.1** — insert — ambiguity — `ad_separation_window_seconds` must be ≥ 0, `avg_slot_impressions` must be positive, else `ERR_INVALID_REQUEST` — `routes/channels.py:54-63`
- **§3.1** — insert — ambiguity — go-live without a qualifying loop → `ERR_INVALID_STATE_TRANSITION` — `routes/channels.py:128-143`
- **§3.1** — insert — ambiguity — channel archive with a current/future PUBLISHED loop → `ERR_INVALID_STATE_TRANSITION` — `routes/channels.py:166-180`
- **§3.1** — insert — ambiguity — ops-run allowed in any lifecycle status; grant-expiry sweep is global (all channels); posture recomputed on checkpoint channel plus every channel with an expired grant — `routes/channels.py:183-209`
- **§3.2** — revise — **mismatch** — grant activation order pinned as window → channel-not-ARCHIVED → content (PRD listed content before channel), with window/channel failures as `ERR_INVALID_STATE_TRANSITION` — `routes/content.py:234-259`
- **§3.2** — insert — ambiguity — reinstate/archive precondition failures → `ERR_INVALID_STATE_TRANSITION` — `routes/content.py:131-155`
- **§3.3** — insert — ambiguity — break removal compacts remaining breaks' `sequence_index` — `routes/loops.py:304-309`
- **§3.3** — insert — ambiguity — break-marking check order duration → overflow → capacity; capacity uses the same floored 25% as validation — `routes/loops.py:246-253`
- **§3.4** — insert — ambiguity — validate evaluates per §2.10 tiers (content tier 9, rights tier 10, tiling/capacity tier 12), not narrative order — `routes/loops.py:330-343`
- **§3.4** — insert — ambiguity — lock with any undecided break → `ERR_INVALID_STATE_TRANSITION` — `routes/loops.py:374-376`
- **§3.4** — revise — **mismatch** — publish increments channel `version` by one, plus a second increment when the posture recompute changes posture — `routes/loops.py:487-490`, `services/core.py:175-177`
- **§3.4** — insert — ambiguity — archiving a not-yet-past loop → `ERR_INVALID_STATE_TRANSITION` — `routes/loops.py:505-506`
- **§3.5** — insert — ambiguity — campaign activation: flight check first, either failure `ERR_INVALID_STATE_TRANSITION` — `routes/campaigns.py:133-143`
- **§3.5** — insert — ambiguity — resume: ended flight → `ERR_INVALID_STATE_TRANSITION`, checked before budget headroom — `routes/campaigns.py:153-161`
- **§3.5** — revise — ambiguity — automatic exhaustion fires only from `ACTIVE` status — `services/core.py:264-269`
- **§3.5** — insert — ambiguity — adjust-budget: positive-integer shape (`ERR_INVALID_REQUEST`), allowed in any status, never by itself exhausts an `ACTIVE` campaign — `routes/campaigns.py:174-194`
- **§3.6** — insert — ambiguity — decision-run guard errors: wrong loop status or break status → `ERR_INVALID_STATE_TRANSITION` — `routes/decisions.py:50-59`
- **§3.6** — insert — ambiguity — re-runs void only provisionals; surviving committed decisions keep occupied slots — `routes/decisions.py:63-67`, `services/selector.py:61-67`
- **§3.6** — insert — ambiguity — decision run returns `201` with created decisions as an array, no pagination fields — `routes/decisions.py:72`, `response.py:53-55`
- **§3.6** — insert — ambiguity — direct ranking: remaining ties broken by creation (insertion) order — `services/selector.py:155-164`
- **§3.6** — insert — ambiguity — house cap counts non-voided placements on date D network-wide including this run; house ranking ties by insertion order — `services/selector.py:185-198`
- **§3.7** — insert — ambiguity — reconciled house decisions also get `actual_impressions` summed from their `AD_IMPRESSION` events — `routes/decisions.py:99-125`
- **§3.7** — insert — ambiguity — non-applicable companion fields (incl. `quantity` on non-`AD_IMPRESSION`) must be absent/null, `watch_seconds` non-negative integer, PlatformAdmin omitting `platform_id` — all `ERR_INVALID_REQUEST` — `routes/events.py:60-89`
- **§3.7** — insert — ambiguity — peak-viewer replay: remaining ties after `created_at` broken by ingestion order — `services/selector.py:295-298`
- **§3.8** — insert — ambiguity — agreement effective end before start → `ERR_INVALID_REQUEST` — `routes/platforms.py:148-149`
- **§3.8** — insert — ambiguity — agreement PATCH mechanics: rate fields and/or `target_status`; neither → `ERR_INVALID_REQUEST`; rate edits past `NEGOTIATION` → `ERR_INVALID_STATE_TRANSITION`; rate edits apply before the status transition — `routes/platforms.py:215-273`
- **§3.8** — revise — **mismatch** — re-activation also requires the channel not `ARCHIVED` (PRD pinned that only for first activation); both activation guard failures are `ERR_INVALID_STATE_TRANSITION` — `routes/platforms.py:256-262`
- **§3.8** — insert — ambiguity — "covering" means the closed effective window contains the whole period month; multiple qualifiers → most recently created wins — `routes/reports.py:43-60`
- **§3.8** — insert — ambiguity — `dispute_reason` recorded on the report's `dispute_reason` field — `routes/reports.py:233-235`, `serializers.py:91-97`
- **§4** — insert — ambiguity — 204 removals return an empty body with no envelope — `response.py:58-59`

No behavior was invented; every pin was traced to a specific implementation line. Tests were consulted only as a cross-reference (e.g., `test_helpers/assertions.py` confirms `version >= 1`), never as authority.
