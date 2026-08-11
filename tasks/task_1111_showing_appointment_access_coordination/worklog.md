# Worklog — task_1111_showing_appointment_access_coordination

## Step 1: Create Task Directory — 2026-08-10T00:00:00.000Z

Task directory pre-assigned at tasks/task_1111_showing_appointment_access_coordination; directory and workspace/ subdirectory already exist. Step 1 auto-index scan skipped per instructions. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-10T18:10:00.000Z

All three artifacts are generated and verified. Final report:

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_1111_showing_appointment_access_coordination/`

**Files (all exist, non-empty, lint-clean):**
- `SCAFFOLD.yaml` (63 KB) — §1.0–§1.7 only; no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (68 KB) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (94 KB) — single top-level key `scaffold_corner_design`

**Domain design** (ShowingTime-style showing coordination, archetype: temporal windowing + multi-party negotiation, flat topology, cyclic state machines, immediate consistency, logical clock defaulting to `2026-05-01T00:00:00Z`):
- **10 entities**: Seller, Agent, Listing, VerificationCase, BlackoutWindow, ShowingRequest, AccessCredential, FeedbackRequest, StrikeRecord, ActivityEvent
- **7 state machines**: ShowingRequest (branching + DECLINED→reschedule cycle + auto-expiry), VerificationCase (REJECTED→SUBMITTED resubmit cycle), Listing (ACTIVE⇄PAUSED→WITHDRAWN with cascade), AccessCredential, FeedbackRequest, Agent standing (threshold-derived cyclic), StrikeRecord
- **42 endpoints**, **44 error codes**, **7 calculations**, **5 roles** (Anonymous/PlatformAdmin opaque; Seller/ListingAgent/BuyerAgent entity-backed), **2 OCC concurrency rules** (listing policy, seller approval settings; both 412)

**Difficulty design: 18 instances** (2 per each of the 9 rules), including:
- Dual-variant calcs on different domains: vacant-vs-occupied access windows (`[09:00,11:30)` vs `[09:45,11:00)` for identical showings) and PROVISIONAL-vs-FINAL seller report rates (0.50 vs 1.00 on identical data)
- Combinatorial formulas in different modes: nested min/max approval deadline with occupancy branch (mode a), pinned per-feedback-round-first feedback rollup (mode b; pinned 4.3 vs forbidden aggregate-first 4.2)
- Depth-3 withdraw cascade and depth-4 no-show→strike→suspension→mass-cancel cascade; two compensating invariants (confirmed_showing_count, active_strike_points); boundary checks on daily cap (count) and credential expiry (timestamp)

**Corner design: 54 instances** (45 active + 9 `excluded_because` stubs) across all 9 taxonomy sections, covering defaults, initial states, invalid transitions, terminal lockdowns, deadline sweeps, RBAC denials, ownership checks, OCC happy/stale paths, pagination, error envelope shape, and immediate consistency.

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (42 endpoints, 10 entities, 18 §1.8 + 45 active §1.9 instances, 603 calls scanned). Instance names unique across both design files; no banned concurrency vocabulary; all formula-derived asserts use pre-computed literals; all `${var}` placeholders trace to prior `captures`. No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-10T18:10:30.000Z

Copied ./INSTRUCTION.md to tasks/task_1111_showing_appointment_access_coordination/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-10T18:30:00.000Z

PRD generation complete. Output verified on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1111_showing_appointment_access_coordination/workspace/PRD.md` (51,812 bytes, 337 lines). The withheld difficulty/corner design files were never opened; no other task directory was inspected.

## Document structure

- **§1 Introduction** — 2 paragraphs (pain-point + system-goal angle; `/showing-desk` mount)
- **§2 Global Specifications** — 12 subsections: 2.1 RBAC (5 roles, per-role identity translation), 2.2 Response Structure (byte-identical verbatim copy of the canonical source — verified `True` by diff), 2.3 Pagination, 2.4 Logical Clock (default `2026-05-01T00:00:00Z`), 2.5 Common Resource Properties (ActivityEvent `common_fields: false` exception stated), 2.6 Nested Path Resolution, 2.7 Validation Pipeline (all 17 priority stages as an ordered list with masking semantics), 2.8 OCC (both rules), 2.9 Cascading Consistency (INV-1/INV-2, CASCADE A/B), 2.10 Temporal/Numeric Precision (half-open vs closed intervals, exclusive `expires_at`, pinned rounding), 2.11 Expiration Sweep (6 pinned steps + 6 output counts), 2.12 Activity Trail (all 19 event types)
- **§3 Business Logic** — 8 subsections (onboarding/verification, listing setup/policy/blackout/withdrawal cascade, intake validation gauntlet, approval/decline/reschedule, confirmation/credentialing, completion/no-show/strikes, feedback scoring, seller reporting)
- **§4 Endpoint table** — 42 rows, exactly 4 columns
- **§5 Error catalogue** — 44 rows, exactly 2 columns; file ends here with no audit footer

## Hard contract reports

```
Field coverage check:
- entities[].fields: 74 required, 74 present, 0 missing
- endpoints[].request_body/input: 38 required, 38 present, 0 missing
- path params + report/clock/sweep output keys: covered (90 identifiers total, 0 missing)
Status: PASS

Rule coverage check:
- validations[] priority pipeline: 17 stages expressed as an ordered list with explicit masking semantics
- concurrency_rules[] OCC: 2/2 (write endpoint + expected_listing_version/expected_seller_version + ERR_STALE_* + HTTP 412 named)
- state_machines[].transitions: all 7 machines expressed (Listing 4, ShowingRequest 12 incl. system cascades, AccessCredential 3, FeedbackRequest 4, VerificationCase 3, Agent_standing 6, StrikeRecord 2), all side-effect hops stated
- calculations[]: 7/7 in precise prose (approval deadline clamp, access-window variants, standing thresholds 15/30, pinned feedback rounding incl. the 4.25/4.25/4.20 → 4.3 vs 4.2 example, daily cap, buffered-overlap vs closed blackout, FINAL/PROVISIONAL report rates)
- validations[] conditions: all 17 matchable to error IDs in §2.7/§3 narrative
- endpoints[].side_effects / applies_to: all expressed (create/reschedule/blackout triple scope for time-range, etc.)
- entities[].fields[] structured content: defaults (240/30/5/120/false), ranges (1..10080, 0..240, 1..20, 0..4320), null-initial fields, computed derivations all reconstructible
- sibling-branch symmetry: approve/decline, pause/resume/withdraw, VACANT/OCCUPIED windows, FINAL/PROVISIONAL, 3 cancel variants — equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 240
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Key rules surfaced

- Auto-approve collapses `approval_deadline` to creation time (born APPROVED) only for VACANT + `auto_approve`; OCCUPIED always requires explicit approval
- Clamp formula for `approval_deadline` (later of +30 min vs earlier of seller timeout and notice-adjusted start), `confirm_by_deadline` = start − 60 min
- Strict-inequality buffered overlap (boundary touch allowed) vs closed-interval blackout (touch conflicts); pipeline order lead-time → overlap → blackout → daily cap
- Full CASCADE A (withdraw) and CASCADE B (no-show → strike 25 → standing → future-request cancellations) hop sequences; INV-1/INV-2 invariants
- Standing ladder inclusive boundaries (15 = RESTRICTED, 30 = SUSPENDED); cascade fires only on transition INTO SUSPENDED; no resurrection on de-escalation
- Pinned feedback rounding order with the divergence example; redeemable window `[active_from, expires_at)`; late-cancel strike under 24 h; strike TTL 90 days
- Additional fidelity checks: no fuzzy/approximating words, no operator pseudocode outside fences, all 44 error IDs and all enum/state values present verbatim.

## Step 5: Generate Unit Tests — 2026-08-10T18:45:00.000Z

**Generated test infrastructure** in `/home/ubuntu/github/CodingPRD/tasks/task_1111_showing_appointment_access_coordination/test_helpers/` (all non-empty, compile clean):

- `types.py` — 10 entity TypedDicts + 13 status/role enums; `ActivityEvent` correctly modeled as append-only (no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 42 PRD endpoints
- `api_errors.py` — `ApiErrorId` enum (45 codes) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` shape checkers + INV-1/INV-2 invariant checkers
- `factories.py` — payload factories (input fields only) with auto-unique names/licenses
- `constants.py` — thresholds from the PRD calculations (weights 25/10, ladders 15/30, TTL 90d, windows 60/15, weights 0.30–0.10, instruction texts)
- `test_users.py` — `TEST_USERS` shared constants + mandatory per-instance `make_<role>_headers(id)` builders for the three entity-backed roles
- `fixtures.py` — 5 tiers: verified-agent onboarding, world builders (vacant-auto / occupied-manual), lifecycle shortcuts (pending/approved/confirmed/completed-via-sweep), strike accumulation helpers, terminal-state worlds
- `__init__.py` — barrel export of framework generics + PRD-specific code

**Test suite** in `test_suite/` — **82 tests, 82 design tags, all resolving**:

- **Queue A (Difficulty)**: 18/18 instances x exactly 2 tests = 36 tests across `test_01`–`test_11` (access-window variants, report variants, approval-deadline min/max formula, feedback rounding order, both state cycles, depth-3 withdraw cascade, depth-4 suspension cascade, both priority pairs, daily-cap and credential-expiry boundaries, both cross-entity gates, both overlap semantics, both compensating invariants)
- **Queue B (Corner)**: 45/45 non-stub instances x ≥1 test = 46 tests across `test_20`–`test_26` (entities 6, state_machines 9, calculations 3 [standing-threshold got 2 tests for the 20-pt/30-pt legs], validations 13, endpoints 4, errors 3, rbac 3, complexity_layers 3, consistency_model 1)

**Skipped instances**: none (PRD-first filter passed everywhere). The 9 `excluded_because:` stubs were not translated; all 9 cross-references verified to resolve to real queue-A instances.

**Verification**: `python3 -m py_compile` passes on all 28 generated `.py` files; `pytest --collect-only` collects 82 tests; a programmatic audit confirmed every tag maps to a real instance with required counts, exactly one tag per test, no unknown tags; and a citation sweep confirmed every docstring's quoted PRD sentence survives literal grep of `workspace/PRD.md`.

## Step 6: Generate Implementation — 2026-08-10T18:45:00.000Z

**Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1111_showing_appointment_access_coordination/workspace/implementation/`)**

| File | Purpose |
|---|---|
| `start.sh` | Executable launcher; guarded `pip install` (no-op once flask importable), `exec python3 app.py` in foreground |
| `requirements.txt` | `flask>=3.0,<4.0` |
| `app.py` | Flask entry point; binds `0.0.0.0:$PORT` (default 10000); error handlers for ApiError/404/405/500 |
| `db.py` | In-memory stores (10 dicts); starts empty — no seeding anywhere |
| `clock.py` | Logical clock, startup default exactly `2026-05-01T00:00:00Z`, never wall-clock; ISO parse/format with 3 fractional digits |
| `errors.py` | All 42 error IDs from the catalogue |
| `response.py` | Envelope: `meta`(`api_request_id` with `req_` prefix, `api_request_timestamp`, +`limit`/`offset`/`total_count`/`has_more` on lists), `response_type` ∈ object/array/error, `data` with `error_id`/`message` on errors |
| `middleware.py` | Stage-1 auth (`X-User-ID`/`X-User-Role`, 5 roles), stage-2 shape validation (unknown-field rejection, typed/datetime/enum checks), role gates, pagination parsing (limit default 10, 1–100; offset ≥ 0) |
| `services/core.py` | Entity factory, `version`/`updated_at` touch, activity-event append, all serializers, cross-entity lookups |
| `services/calc.py` | All 7 calculations + cascades + six-step sweep |
| `routes/sellers.py` | 3 endpoints (create, get, OCC approval-settings) |
| `routes/agents.py` | 7 endpoints (register, get, verification cases submit/list/review/resubmit, strikes list/forgive) |
| `routes/listings.py` | 11 endpoints (CRUD, policy OCC, pause/resume/withdraw, blackout create/list/delete, activity events, activity report) |
| `routes/showing_requests.py` | 13 endpoints (intake, get/list, approve/decline/confirm/cancel/reschedule/declare-no-show, credentials issue/list, strikes, feedback-request, activity-events) |
| `routes/credentials_feedback.py` | 3 endpoints (redeem, revoke, feedback submit) |
| `routes/ops.py` | 2 endpoints (clock set, expiration sweep) |

**Endpoints registered: 42** (matching the scaffold's endpoint table exactly; orchestrator independently verified all 42 (method, path) pairs match SCAFFOLD.yaml with path-param names normalized).

**Key design decisions**

- **Validation pipeline order** (PRD §2.7) enforced literally in every handler: auth → shape → role → existence (path left-to-right, then body FKs) → ownership → OCC → state → agent eligibility → time-range → lead-time → buffered-overlap → blackout → action-deadline → daily-cap → credential-uniqueness → open-case → no-show-declarability. Observed example: `ERR_INSUFFICIENT_LEAD_TIME` (422) fires before `ERR_SHOWING_OVERLAP_CONFLICT` (409).
- **Approval deadline**: `max(created+30m, min(created+timeout, start−min_notice))`; collapses to `created_at` with birth in APPROVED when VACANT + `auto_approve`. Verified numerically in smoke test.
- **Interval semantics**: showing windows half-open; buffered overlap strict (`<`) so touching at padded boundary is allowed (verified); blackout closed-interval with `<=` so touching counts (verified); credential redeemable `[active_from, expires_at)`.
- **Feedback scoring**: pinned round-each-then-average with `Decimal`/`ROUND_HALF_UP` (verified: q=(5,4,4,3,5) → 4.3); report rates at 2dp half-up, FINAL nulls `provisional_completion_rate`.
- **Cascades**: CASCADE A (withdraw → cancel live requests → revoke ISSUED credentials → cancel SCHEDULED feedback, per-entity version bumps); CASCADE B (no-show/late-cancel strike → standing recompute → only on *transition into* SUSPENDED, cancel agent's future requests with full CONFIRMED unwind; no resurrection on de-escalation).
- **Sweep**: six pinned steps; CONFIRMED+USED-credential → COMPLETED flips SCHEDULED feedback to SENT in the same step (counts verified: `requests_completed_count`, `feedback_sent_count`).
- **OCC**: `expected_listing_version`/`expected_seller_version` → 412 with the exact scaffold error IDs (verified both).
- **Storage**: pure module-level dicts; fresh-boot emptiness verified by restarting the server and listing (empty, `total_count: 0`, clock back at default).

**Verification performed**

- `python3 -m py_compile` on all 14 `.py` files: OK
- `start.sh` executable, reads `$PORT`, binds `0.0.0.0`, `exec` foreground, guarded install: confirmed on disk
- Smoke-booted twice (fresh process each time); 59 scripted end-to-end assertions passed (one self-test arithmetic expectation was wrong — the implementation's `2026-05-01T04:00:00.000Z` matches the PRD formula exactly); 7 additional edge-case assertions passed on a fresh boot (decline→reschedule cycle, sweep expiry, activity trail ordering, approval-deadline 422, blackout touch conflict, daily cap 409).
- Test servers stopped; `__pycache__` cleaned.

## Step 7: Run Tests and Iterate — 2026-08-10T19:15:00.000Z

All 8 parallel rounds pass 82/82. The task is complete.

**Iterations run:** 2 sweeps (8 parallel rounds each). Round 1: 24 unique failures (all deterministic, 8/8). Round 2: 3 failures. Round 3 (final): all 8 rounds 82/82 clean.

**Tests deleted:** none. Every failure traced to a PRD-verbatim rule; the union set was fixed, not deleted.

**Fixes applied to `workspace/implementation/`:**

1. `clock.py` — added `fmt_minute()` (ISO 8601 UTC, no fractional digits). PRD §2.10 states "Scheduling arithmetic is performed at minute precision and all timestamps are ISO 8601 in UTC," and the PRD's only literal scheduling timestamp (the startup clock `2026-05-01T00:00:00Z`) is short-form, while §2.2/§2.5 explicitly scope "three fractional digits" to `api_request_timestamp`, `created_at`, and `updated_at` only. The implementation had been rendering every timestamp with `.000Z`.
2. `services/core.py` — added `_iso_minute()` and switched all domain/scheduling fields to it (`start_at`, `end_at`, `approval_deadline`, `confirm_by_deadline`, `active_from`, `expires_at`, `redeemed_at`, `sent_at`, `due_at`, `submitted_at`, `reviewed_at`, `cancelled_at`, `completed_at`); kept 3-fractional `fmt` for `created_at`/`updated_at`. (12 tests fixed.)
3. `routes/ops.py` — `set_clock` now renders `current_utc` via `fmt_minute`.

**Fixes applied to `test_suite/` (test bugs, each made more PRD-faithful):**

4. `test_05_state_cycles.py` (2 sites), `test_26_occ_and_consistency.py` (3 sites), `test_25_error_envelope_and_rbac.py` (1 site), `test_23_validation_corners.py` (2 sites), `test_20_entities.py` (2 sites) — added `expected_status=201` to `validate_success()` calls on create endpoints; PRD §4 states verbatim "Operations that create a new resource return `201 Created`", and sibling tests already passed `expected_status=201`. (10 tests fixed.)
5. `test_04_feedback_rounding.py` — `_setup_three_completed_showings` scheduled showings at 10:00/12:00/14:00, but the second intake ran at clock 10:05 leaving a 115-minute gap, violating the PRD's default `min_notice_minutes` of 120 ("the gap between now and `start_at` must be at least `min_notice_minutes`"); respaced windows to 10:00/13:00/16:00 with matching redeem/sweep times. Also fixed the third feedback payload: uniform `q=(4,4,4,4,4)` yields raw 4.0 under the PRD weights (0.30/0.25/0.20/0.15/0.10), not the claimed 4.20; changed to `q3=5` (raw exactly 4.20) so the test reproduces the PRD's pinned divergence example (raws 4.25/4.25/4.20 → 4.3 pinned vs 4.2 aggregate-first). The implementation had computed 4.0 and the pinned-order 4.2 average correctly all along. (2 tests fixed.)
6. `test_23_validation_corners.py` — `test_confirm_deadline_passed_rejected` called `approve_request` without importing it (NameError); added the import. (1 test fixed.)

**Key finding:** no implementation logic bugs survived — the arithmetic (approval-deadline clamp, feedback rounding order, lead-time enforcement) was PRD-correct; failures were a pervasive timestamp-rendering mismatch plus test-side status-code/fixture/import defects.

Orchestrator verification: all 8 results files exist on disk, each passed=82 total=82 failed=0.

## Step 8: Finalize PRD — 2026-08-10T19:25:00.000Z

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1111_showing_appointment_access_coordination/workspace/PRD_FINALIZED.md`

**Line counts and % delta:**
- `PRD.md`: 337 lines
- `PRD_FINALIZED.md`: 337 lines
- % delta: 0% (in-place revision of one paragraph in §2.10; no lines added or removed)

### Step-7 diff triage

Of the six step_7_diff items, only items 1–3 (timestamp rendering) required a PRD patch. Items 4, 5, 6 were pure test-side bugs where the PRD already pinned the correct behavior and the implementation already matched the PRD:
- Item 4 (expected_status=201 on creates): PRD §4 already states "Operations that create a new resource return `201 Created`" verbatim; impl (`routes/agents.py:46,88`, `routes/listings.py:78,228`, `routes/showing_requests.py:119,379`, `routes/sellers.py:37`) returns 201 on all creates. No edit.
- Item 5 (`min_notice_minutes=120` default; feedback weights 0.30/0.25/0.20/0.15/0.10 and raws 4.25/4.25/4.20 → 4.3): both pinned in PRD §3.2 and §3.7 already. No edit.
- Item 6 (test NameError import): pure test bug. No edit.

### Changes applied

- **§2.10 — revise — added one sentence pinning the rendering precision of every non-system timestamp to minute-precision/no-fractional-digits, and explicitly carving out `api_request_timestamp`/`created_at`/`updated_at` (already pinned to three fractional digits in §2.2/§2.5); named the affected fields exhaustively (blackout/showing `start_at`/`end_at`; showing `approval_deadline`/`confirm_by_deadline`/`cancelled_at`/`completed_at`; credential `active_from`/`expires_at`/`redeemed_at`; feedback `sent_at`/`due_at`/`submitted_at`; verification-case `reviewed_at`; strike `expires_at`; clock-endpoint `current_utc`). — `implementation/clock.py:50` (`fmt_minute`), `implementation/services/core.py:54-56` (`_iso_minute`) applied at `core.py:113, 125, 126, 139, 140, 144, 145, 148, 149, 164, 165, 167, 179, 180, 188, 203`, `implementation/routes/ops.py:23`**

### Per-edit pre-edit search log

**Edit 1 (the only edit) — §2.10 rendering-precision sentence**

- (a) **Subject:** serialization format (precision) of domain/scheduling timestamps in API response payloads, and of `current_utc` in the set-clock response. Distinct from (i) input parsing, which `clock.parse_iso` handles with arbitrary precision, and (ii) the three system-managed timestamps already pinned to 3 fractional digits by §2.2/§2.5.
- (b) **Impl paths enumerated and read/grepped:**
  - `implementation/clock.py:39-47` (`fmt`, 3-fractional) and `clock.py:50-64` (`fmt_minute`, no fractional).
  - `implementation/services/core.py:49-56` (`_iso`/`_iso_minute` dispatchers).
  - `implementation/services/core.py` — every serializer: `verification_case_view` (line 113 `reviewed_at`), `blackout_window_view` (125–126), `showing_request_view` (139, 140, 144, 145, 148, 149), `credential_view` (164, 165, 167), `feedback_view` (179, 180, 188), `strike_view` (203), `activity_event_view` (213 — only `created_at`, no domain timestamps), plus all `created_at`/`updated_at` lines via `_iso`.
  - `implementation/routes/ops.py:23` — `current_utc` rendered via `fmt_minute`.
  - `implementation/response.py:20` — `api_request_timestamp` rendered via `fmt` (3-fractional).
  - Global grep for `fmt_minute|fmt(|_iso_minute|_iso(` confirms no other rendering sites exist; the partition is total.
- (c) **Wording adjustment:** Initial draft considered a bare "domain timestamps are rendered at minute precision." That risked a false universal claim if any other emitted timestamp existed off the enumerated paths. Final wording (i) explicitly limits the 3-fractional set to the three fields §2.2/§2.5 already pin, (ii) names every minute-precision field exhaustively as observed in `_iso_minute` call sites, (iii) includes `current_utc` because `ops.py:23` emits it via `fmt_minute`, and (iv) says nothing about input parsing, leaving `parse_iso`'s acceptance of fractional input untouched.

## Step 9: Complete PRD — 2026-08-10T19:45:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1111_showing_appointment_access_coordination/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, then edited in place; `PRD_FINALIZED.md` untouched).

**Size:** PRD_FINALIZED.md 337 lines / 52,582 chars → PRD_COMPLETED.md 338 lines / 57,790 chars. Char delta: +5,208. All changes are inline paragraph inserts/revisions; no new sections, no deleted requirements.

**Counts:** 25 change hunks — 24 ambiguity-pins, 1 mismatch-revision (the no-show timing boundary; two hunks each carry a secondary pin, noted below).

**Per-change log:**

- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock — `implementation/response.py:20`
- §2.2 — insert — ambiguity — routing-level failures use the error envelope with `ERR_INVALID_REQUEST` at HTTP 404 (undefined route) / 405 (unsupported method), a stated exception to the §5 mapping — `implementation/app.py:31-38`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` 400; query-param checks run after auth/role/path-existence — `implementation/middleware.py:120-144`
- §2.3 — insert — ambiguity — only the listing and showing-request collections reject unknown query params / bad `status` filter values; other list/report endpoints ignore them — `implementation/routes/listings.py:95-102`, `implementation/routes/showing_requests.py:136-145`
- §2.3 — insert — ambiguity — `has_more` = `offset + page_size < total_count` — `implementation/response.py:40`
- §2.4 — revise — ambiguity — clock endpoint returns a standard success envelope whose `data` carries `current_utc` — `implementation/routes/ops.py:23`
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — `implementation/services/core.py:20-21`
- §2.7 stage 2 — insert — ambiguity — no-payload transition POSTs accept absent/empty body; decline/cancel/forgive still validate optional `reason` when a body is present; other transitions ignore the body — `implementation/middleware.py:46-62`, `implementation/routes/showing_requests.py:192-194,296-297`, `implementation/routes/agents.py:189-191`
- §2.7 stage 5 — insert — ambiguity — ownership stage applies exactly to writes/state-transitions plus the Seller self-read; all pure reads are role-gated only, never ownership-gated — e.g. `implementation/routes/listings.py:281-285` (no owner check) vs `implementation/routes/sellers.py:52-54`
- §2.8 — insert — ambiguity — expectation-field-only guarded update is valid and still bumps version — `implementation/routes/listings.py:132-143`
- §2.11 — insert — ambiguity — within each sweep step, candidates processed in creation order — `implementation/services/calc.py:313,322,332,360,372,379`
- §2.12 — revise — ambiguity — `SYSTEM` actor also covers automatic in-call consequences (cascade cancellations/revocations, strike issuance), not only clock/sweep actions — `implementation/services/calc.py:127-128,134,153`
- §3.1 — insert — ambiguity — out-of-range `approval_timeout_minutes` rejected `ERR_INVALID_REQUEST` 400 at onboarding and update; on update the range check runs after the version check — `implementation/routes/sellers.py:27-29,77-81`
- §3.1 — insert — ambiguity — duplicate `license_number` rejected `ERR_INVALID_REQUEST` 400 — `implementation/routes/agents.py:33-36`
- §3.1 — insert — ambiguity — resubmission leaves prior `reviewed_at`/`review_notes` in place — `implementation/routes/agents.py:161-164`
- §3.2 — insert — ambiguity — out-of-range policy knobs rejected `ERR_INVALID_REQUEST` 400; at creation after seller-existence, on policy update after the version check — `implementation/routes/listings.py:36-39,62-64,128-141`
- §3.2 — insert — ambiguity — pause/resume from the wrong non-terminal state fails `ERR_LISTING_NOT_ACTIVE` 409 — `implementation/routes/listings.py:155-157,174-176`
- §3.2 — insert — ambiguity — blackout windows need only pass time-range sanity; past windows allowed — `implementation/routes/listings.py:217-220`
- §3.2 — insert — ambiguity — cascades walk requests in creation order, running each request's full unwind (revoke+event, feedback cancel, then its `CANCELLED` event) before the next; same for the suspension cascade — `implementation/services/calc.py:109-135,254-257`
- §3.3 — insert — ambiguity — intake requires caller's `X-User-ID` to resolve to a registered Agent else `ERR_AGENT_NOT_FOUND` 404, checked alongside body-FK existence ahead of the listing-state check — `implementation/routes/showing_requests.py:83-85`
- §3.4 — insert — ambiguity — terminal-first discipline generalized: every showing-request action rejects terminal requests with `ERR_SHOWING_ALREADY_TERMINAL` before the specific state check — `implementation/routes/showing_requests.py:162-165` and all action call sites
- §3.4 — insert — ambiguity — decline is not time-boxed by `approval_deadline` — `implementation/routes/showing_requests.py:199-208` (no clock check)
- §3.4 — insert — ambiguity — reschedule recomputes deadlines treating the reschedule moment as creation time — `implementation/routes/showing_requests.py:234-236`
- §3.6 — revise — mismatch — no-show declarable only when now is strictly later than `end_at` (at exactly `end_at` → `ERR_NO_SHOW_TOO_EARLY`); PRD's "after the window closes" admitted the half-open-boundary reading — `implementation/routes/showing_requests.py:322-325`
- §3.6 — insert — ambiguity — no-show leaves the request's credential and SCHEDULED feedback untouched — `implementation/routes/showing_requests.py:329-337`
- §3.6 — insert — ambiguity — cancel from DECLINED fails `ERR_SHOWING_NOT_PENDING_APPROVAL` 409 — `implementation/routes/showing_requests.py:303-306`
- §3.6 — insert — ambiguity — expensive (CONFIRMED) buyer-cancel appends the request's `CANCELLED` event last, after the strike leg — `implementation/services/calc.py:290-294`
- §3.7 — insert — ambiguity — feedback-of-showing endpoint answers with a paginated list envelope of zero or one elements — `implementation/routes/showing_requests.py:409-419`
- §3.8 — insert — ambiguity — invalid `mode` rejected `ERR_INVALID_REQUEST` 400; report payload echoes `mode` — `implementation/routes/listings.py:301-305`, `implementation/services/calc.py:419`
- §3.8 — insert — ambiguity — listing-level feed rejects out-of-taxonomy `event_type` with `ERR_INVALID_REQUEST` 400; per-request feed returns an empty page instead — `implementation/routes/listings.py:265-278` vs `implementation/routes/showing_requests.py:431-433`

**Notable already-pinned behaviors verified with no change needed:** approval-deadline clamp formula, confirm-by = start−60m, auto-approve collapse, access-window variants and instruction strings, strike weights/standing ladder/90-day TTL, cascade hop contents, feedback weighting and round-then-average order, report rate formulas, sweep step predicates and boundary operators, error catalogue statuses.
