# Worklog — task_1996_demolition_contracting_salvage

## Step 1: Create task directory — 2026-08-15T05:27:00.000Z

Pre-existing per operator instruction: `tasks/task_1996_demolition_contracting_salvage/` and `workspace/` were created before pipeline start; Step 1 skipped by directive.

## Step 2: Generate scaffold — 2026-08-15T06:35:47.000Z

All three scaffold artifacts are generated, validated, and lint-clean. Summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

## Counts (SCAFFOLD.yaml)
- **Entities: 13** — Project (compound phase × work_posture), StructureSurvey, HazmatAbatement, UtilityDisconnect (dual parallel state dims), DemolitionPermit, EngineeringSurvey (revision cycle), SalvageManifest, SalvageItem, NeighborNotification, DustNoiseLog (append-only event, `common_fields: false`), DebrisTicket, BackfillPlan, FinalInspection
- **State machines: 12** (all entities except SalvageItem; Project carries parallel dimensions + regression cycles; EngineeringSurvey/UtilityDisconnect/HazmatAbatement/FinalInspection/SalvageManifest all cyclic)
- **Calculations: 7** (salvage_valuation, erosion_coverage, dust_exposure_score, diversion_rate, permit_fee, notification_wait_window, permit_expiry_sweep)
- **Endpoints: 45** (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- **Errors: 31**; **Validations: 15 ordered priorities**; **Roles: 14** (all opaque, segregation-of-duties model with 3 X-User-ID SoD pairs); **Concurrency rules: 2** (OCC on Project.version engineering-pin, on DemolitionPermit.version renewal — both pass the serial-observability filter)
- **§1.8 difficulty instances: 26** (dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear 3, cascade 3, priority-conflict 3, boundary 4, cross-entity 4, temporal-overlap 2, invariant 2)
- **§1.9 corner instances: 62** (49 active + 13 `excluded_because` stubs) across all 9 guide sections; 1,052 total recipe calls lint-scanned

## Harder-than-expert scaling applied
- Exceeded the ≥2/rule floor: 3–4 instances on five rules; all three combinatorial modes (tiered multi-input dust formula, pinned sum-then-divide rounding for diversion rate, circular-looking permit-fee tier selection) with hand-computed literal asserts (e.g. fee 715000, diversion 0.4455 vs the rejected 0.65 averaging)
- Three **depth-3 transitive cascades from different trigger classes**: API-driven engineering-revision → project revert → notification void; clock-driven permit expiry → project revert → ticket cancellation with tonnage moves; monitor-driven dust exceedance → STOPPED posture → inspection cancellation
- Four boundary instances on distinct metrics/endpoints (exposure 75.0 `>=`, diversion exactly 0.5000 at closure, compaction 95.0, 72h wait window to the second) plus empty-set boundaries (zero notifications, zero disconnects, empty manifest)
- Three validation priority conflicts on three different category pairs (state>safety, safety>temporal, referential>fiscal)
- Two compensating invariants with literal step-by-step conserved quantities (debris mass M=16.0 through receive+void; salvage net-credit identity through amend cycle)
- Version-pinned approval (engineering pin goes stale on revision), parallel state dimensions on two entities, and a full release gate ordering 8 prerequisite checks

**Verification:** `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Additional audits passed: no forbidden concurrency vocabulary, all 86 instance names unique across both files, all grounds refs resolve, all 31 error codes have test coverage, no sibling task was read.

## Step 3: Copy INSTRUCTION.md — 2026-08-15T06:35:47.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1996_demolition_contracting_salvage/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T06:56:42.000Z

Generation complete. All three hard contracts pass, verified programmatically against the scaffold.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/workspace/PRD.md` — 339 lines, generated purely from `SCAFFOLD.yaml` plus the doc-generator skill spec (the two forbidden design-index files were never opened; no sibling tasks consulted).

**Section inventory**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (14 roles, opaque-identity prose naming each role), 2.2 API Response Structure (verbatim copy of `section-2.2-response-structure.md` — byte-verified), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 Resource Identity/Common Fields/Logical Clock (incl. DustNoiseLog append-only exception carrying only `id`+`created_at`, clock default `2026-08-01T00:00:00Z`), 2.5 Numeric Precision (integer cents, 3-decimal tons, 4-decimal round-half-up ratios, 1-decimal exposure), 2.6 OCC (both rules with exact `error_id`/HTTP 412), 2.7 Parallel State Dimensions/Cascades/Nested Resources, 2.8 Segregation of Duties (3 SoD pairs), 2.9 Validation Order of Evaluation (priorities 1–12 with all sub-orders)
- §3 Business Logic (9 subsections, lifecycle-timeline grouping): 3.1 Project Setup & Surveys, 3.2 Abatement, 3.3 Utilities & Permit (tiered fee with pinned evaluation order, expiry sweep), 3.4 Engineering & Pin (stale-pin cascade), 3.5 Salvage dual-variant valuation & amend cycle, 3.6 Notifications (blackout → quiet-hours → daily-cap sub-order, 72h inclusive boundary), 3.7 Release Gate (8 ordered checks), 3.8 Active Demolition (dust score bands/cap/threshold, STOPPED cascade, resume, debris ledger with sum-first-round-once diversion math and mass invariant), 3.9 Backfill/Erosion/Closure (provisional vs final coverage, 0.9000 gate, PASS preconditions)
- §4 Endpoint table — 45 rows, 4 columns only (Method, Path, Description, Authorized Role(s))
- §5 Error catalogue — 31 rows, 2 columns only; document ends there, no audit footer

**Contract 1 — Field coverage** (automated, scaffold-parsed vs PRD backticks; two passes — first pass caught a regex artifact and a real fix for `PASSED`/`FAILED`):
- entities[].fields: 100 required, 100 present, 0 missing
- endpoints[].request_body: 63 required, 63 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing (plus `limit`/`offset`)
- endpoints[].path_params: 1 required (`id`), 1 present, 0 missing
- Status: PASS

**Contract 2 — Rule coverage** (walked all six high-risk categories + tail against the scaffold):
- validations[] priority ordering (12 tiers incl. release sub-order, delivery-timing sub-order): expressed in §2.9 and §3.6/§3.7, 0 missing
- concurrency_rules[] OCC: 2/2 expressed with write_endpoint + `expected_project_version`/`expected_permit_version` + `ERR_STALE_VERSION`/412, framed purely as stale-version rejection, 0 missing
- state-machine transitions: all 40+ rendered with from/to states, preconditions paired to error IDs, and every side effect (incl. version bumps, cascades, counter moves, symmetric sibling branches: abatement re-START, utility re-VERIFY, permit re-SUBMIT, ticket VOID from two states, RECONCILE from two states, FINALIZE from DRAFT/AMENDED, REQUEST_REVISION from SUBMITTED vs CERTIFIED), 0 missing
- calculations[]: 7/7 in precise prose (permit fee tiers, dust exposure bands, diversion ratio, erosion ratios, wait window, expiry sweep, salvage variants) — no pseudocode, no fuzzy words (scanned), reconstruction-safe
- endpoints[] side_effects / applies_to scopes: all expressed (incl. sweep on clock-set and permit/project interaction, release's 8-check chain, delivery's 3 checks)
- entities[].fields[] structured content (defaults, signs, enums, initial values): reconstructible from prose — 93/93 enum/state values present as exact strings
- Status: PASS

**Contract 3 — §3 path purity**: 566 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. Status: PASS

## Step 5: Generate unit tests — 2026-08-15T07:26:00.000Z

Done. Summary of the generation for `task_1996_demolition_contracting_salvage`:

## Test counts

**104 tests total, all with exactly one `Design:` tag, all tags resolving to real instances.**

- **Queue A (Difficulty)**: 26/26 instances covered, each with ≥2 tests → **54 tests**
- **Queue B (Corner)**: 35/35 non-stub instances covered, each with ≥1 test → **50 tests**
- **Corner stubs**: 13 `excluded_because:` stubs not translated (correct); all 13 cross-references verified to resolve to real difficulty instances.

## Instances skipped

**None.** Every non-stub instance passed the PRD-first two-condition filter — PRD.md is unusually thorough (the validation priority order is verbatim in §2.9, all thresholds in §2.5, all formulas in §3), so every asserted outcome has verbatim PRD coverage and unique derivability. Two assertions inside translated tests were deliberately narrowed where PRD leaves a design space: `finalized_at` timestamp-value equality after re-FINALIZE (only "stamps from the logical clock" is pinned) and exact list-order of the delivered notification (list order is by `created_at`, not `delivered_at`) — the tagged instance's core assertion is kept verbatim in each case.

## test_helpers/ inventory

- `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/test_helpers/__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 20 status/enum classes, role enum, 14 entity TypedDicts (DustNoiseLog correctly omits `updated_at`/`version` per its append-only nature)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (32 methods incl. `/_clock/set_current_utc`)
- `api_errors.py` — 31 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_mass_invariant`
- `factories.py` — 14 payload factories, input fields only
- `constants.py` — `THRESHOLDS`, `PERMIT_FEE`, `WIND_FACTOR_TIERS`, `TEST_DEFAULTS` from PRD §2.5/§3.3/§3.8
- `test_users.py` — `TEST_USERS` for all 14 roles (all opaque identity) + per-role `make_*_headers` builders for SoD chains
- `fixtures.py` — composite helpers: `setup_preconditions_pending` → `setup_release_ready` → `setup_released_project` → `setup_demolition_active` → `setup_debris_clearance` → `setup_backfill_phase` → `setup_final_review`, plus atomic helpers (`create_confirmed_disconnect`, `create_active_permit`, `create_certified_engineering_survey`, `pin_engineering_survey`, `append_dust_log`, `stop_project_with_exceedance`) with distinct SoD operator ids

## test_suite/ inventory

- `conftest.py` — session `api` fixture + 14 role-header fixtures
- `test_01_envelope_auth_rbac.py` — envelope shapes, project defaults, computed-input ignore, auth 401, 4 RBAC denials, 3 SoD rejections
- `test_02_surveys_abatement_utilities.py` — survey auto-advance/bubble-up/regression, required-field/404, abatement recycle, FK listing, utility dual-dimension cycle, half-open window adjacency, pagination, project list filter
- `test_03_permits.py` — fee tier evaluation order (4 areas), duplicate permit, REJECTED lockdown, ACTIVATE utility gates, renewal OCC + expiry sweeps, startup default clock
- `test_04_engineering_pin_release.py` — engineering revision cycle, pin OCC, full release gate (priority pairs, zero/undelivered notifications, missing pin, permit-not-active, 72h boundary ±1s), stale-pin and re-pin, depth-3 revision cascade
- `test_05_dust_posture_diversion.py` — tiered wind formula, 75.0 boundary (below/at/above), raw cap, append-only log shape, stop/resume cycle, posture gates, phase gate for tickets, sum-then-divide diversion, GOLD boundary, RECEIVE idempotency, weight/delta-cap validations, mass invariant
- `test_06_salvage.py` — dual-variant divergence (CONSERVATIVE/OPTIMISTIC), empty-manifest rejection, amend-cycle money invariant, negative-quantity gating
- `test_07_notifications.py` — blackout date, quiet-hours occupation window (07:00/18:30 allowed, 18:45/23:00 rejected), daily cap (3rd allowed, 4th rejected, next-day success)
- `test_08_backfill_closure.py` — provisional-vs-final erosion divergence, 0.9000/compaction boundaries, START_BACKFILL gate, referential-beats-fiscal priority, diversion closure boundary (0.5 pass / 0.4917 fail), fail-reschedule-pass cycle, inspection-outstanding, version increments, immediate consistency
- `test_09_cross_entity_gates.py` — abatement REQUEST_CLEARANCE gated by parent survey state

## Stage 2 self-check results

- Design-tag audit: 104/104 tests exactly one tag; 0 unresolved; 0 stub-tagged. Difficulty ≥2 everywhere; corner ≥1 everywhere (script-verified).
- Verbatim-citation grep: every test's quoted PRD fragment contains a ≥8-word window found literally in PRD.md (whitespace-folded) — 0 failures.
- All error IDs asserted are named in PRD prose with trigger conditions (not just the §5 table); priority-ordering tests cite the explicit §2.9 ordering.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- No "scaffold"/table/§1.x references in generated code.
- All modules compile and import cleanly (`test_suite.conftest` + all 9 test modules).

## Step 6: Generate implementation — 2026-08-15T08:04:50.000Z

Implementation complete and verified. (Note: the subagent was terminated once by a transient API 429 rate-limit mid-verification and was resumed; it completed on resume.)

## File inventory — `tasks/task_1996_demolition_contracting_salvage/workspace/implementation/`

- `start.sh` (executable) — guarded dependency install (`if ! python3 -c "import flask"`), then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, blueprint registration, `before_request` permit-expiry sweep on every `/demolition/*` call, error handlers (ApiError → envelope; 404 → `ERR_NOT_FOUND`; 400 → `ERR_VALIDATION`), runs on `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory `Store` (13 entity dicts, logical clock starting exactly `2026-08-01T00:00:00Z`, insertion sequence), `new_record()` (UUID + created_at/updated_at/version=1), `touch()` (version+1, updated_at refresh). No seeding anywhere — store starts empty every boot (verified: after kill+reboot, `GET /demolition/projects` returns `total_count: 0`)
- `errors.py` — `ApiError` + all 30 catalog error IDs with their HTTP statuses
- `util.py` — timestamp formatting (ISO 8601 UTC, 3 fractional digits), ISO datetime parsing (naive → 400), `round4`/`round1` (Decimal ROUND_HALF_UP), body validation helpers, 3-decimal tonnage check
- `response.py` — envelope helpers: success `{meta: {api_request_id: "req_…", api_request_timestamp}, response_type, data}`; list responses add `limit/offset/total_count/has_more` to meta; error body `{error_id, message}`. Pagination: limit default 10 clamped [1,100], offset default 0, sort by `created_at` asc with insertion-order tiebreak
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (unknown role → 401 `ERR_UNAUTHENTICATED`), per-endpoint role lists (403 `ERR_FORBIDDEN`), per-action role splits inside shared transition endpoints
- `serializers.py` — JSON serialization for all 13 entities (DustNoiseLog omits `updated_at`/`version` per append-only rule)
- `services.py` — lookups (404), calculation helpers, cascades (release-readiness-lost, permit-expired-under-active, inspection-cancel-on-stop), `run_permit_expiry_sweep()`
- `routes/` — `projects.py`, `surveys.py`, `utilities.py`, `permits.py`, `engineering.py`, `salvage.py`, `notifications.py`, `dust.py`, `tickets.py`, `backfill.py`, `inspections.py`, `clock.py`

## Endpoint count
45 endpoints — all 45 from the scaffold table (the 46th URL-map rule is Flask's default static route).

## The 7 calculations

1. **salvage_valuation** — `optimistic_total_cents`/`conservative_total_cents` recomputed over ALL items (signed amendment lines included) on every item add; `net_credit_cents = policy_total − processing_fee_cents` recomputed on FINALIZE and on each AMENDED item add (kept invariant across the amend cycle; left untouched while DRAFT so an AMEND round-trip preserves the invariant). `extended_value_cents = quantity × (high|low)` per manifest policy. Integer cents, no rounding.
2. **erosion_coverage** — provisional at APPROVE and final at VERIFY_EROSION, both `Decimal` division quantized to 4 places with ROUND_HALF_UP; final gates at exactly `>= 0.9000`.
3. **dust_exposure_score** — wind factor brackets (0.5 / 1.0 / 1.6 / 2.4 at <5, ≤12, ≤20, >20), `raw = value × factor × hours`, cap at 1000, divide by 10, round half-up to 1 decimal; exceedance at `>= 75.0` (boundary inclusive, verified); every event accumulates into `cumulative_exposure_score`; exceedance in the four active phases flips `work_posture` to STOPPED and cancels SCHEDULED inspections (project version +1).
4. **diversion_rate** — nested-rounding order: full-precision Decimal sums of `disposed_tons`/`diverted_tons` over RECEIVED/DISPUTED/RECONCILED first, single ROUND_HALF_UP to 4 places at the end, 0 when denominator is 0; tier GOLD ≥ 0.7500 / SILVER ≥ 0.5000 / STANDARD. Counters moved per ticket event (RECEIVE/RECONCILE-by-delta/VOID from MANIFESTED/VOID from RECEIVED/system CANCEL); mass invariant verified (in_transit + landfill + diverted + removed == Σ gross including voided/cancelled).
5. **permit_fee** — pinned evaluation order: provisional subtotal `150000 + 12 × sqft` selects the tier (≥ 500000 → TIER2), final fee `150000 + sqft × (12|18) + (25000 if TIER2)`. Both sides of the boundary verified (29166 → 499992 TIER1; 29167 → 700006 TIER2). Computed once at creation, never changes.
6. **notification_wait_window** — `max(delivered_at) over DELIVERED + 72h`; allowed when `now >=` that instant (inclusive boundary verified at exactly +72h), evaluated on release and re-checked on START_DEMOLITION.
7. **permit_expiry_sweep** — runs on `POST /_clock/set_current_utc` and on every `/demolition/*` interaction; ACTIVE → EXPIRED only when `expires_at < now` (equality is NOT expired — boundary verified); cascades RELEASED → PRECONDITIONS_PENDING (voiding PENDING notifications, keeping the stale pin) and DEMOLITION_ACTIVE → PRECONDITIONS_PENDING (MANIFESTED tickets → CANCELLED with counter moves).

## start.sh contract
Confirmed: `start.sh` is executable, `exec`s `python3 app.py` in the foreground, and `app.py` binds `host="0.0.0.0"`, `port=int(os.environ.get("PORT", "10000"))`. The pip install is guarded so per-test reboots are no-ops. Boot-to-HTTP was ~1s in testing.

## Verification performed
Four live smoke suites (~120 assertions, all passing): full happy path to CLOSED; auth/RBAC/SoD on all three segregated steps; OCC 412 on pin and renewal; release-gate sub-order (including state-legality 409 before prerequisites); quiet-hours boundaries (18:29:59 ok / 18:30:00 ok / 18:30:01 blocked / 06:30 blocked / 07:00 ok); blackout date; daily cap; 72h boundary; permit expiry boundary and both expiry cascades; pin-stale cascade with re-pin and re-release; ticket receive/dispute/reconcile/void accounting with delta-cap and weight checks; dust exceedance stoppage + resume; backfill compaction/erosion gates; inspection FAIL/RESCHEDULE/PASS with backfill and diversion gates (0.8 boundary inclusive); salvage finalize/amend invariant; validation-priority spot checks (body-shape 400 before path 404; 400 before state 409); and fresh-reboot emptiness.

## Step 7: Test-iterate loop — 2026-08-15T08:40:26.000Z

All 8 rounds pass 104/104. The task is complete.

---

## Summary

**Iterations run:** 2 (initial sweep surfaced 8 deterministic failures, identical across all 8 rounds — no flakiness; fixes applied; second sweep clean 8/8 × 104/104).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/test_helpers/assertions.py` — added `assert_iso8601_instant(actual, expected_iso)` helper. Why: PRD §2.4 pins the *instant* of server-stamped timestamps ("always taken from this logical clock") but pins the three-fractional-digit string form only for `created_at`/`updated_at` (§2.4) and `api_request_timestamp` (§2.2). Stamped fields (`activated_at`, `expires_at`, `delivered_at`, `recorded_at`) may faithfully serialize as either `...Z` or `....000Z`; the helper compares parsed instants, keeping the PRD-pinned assertion while dropping the unpinned format assertion (STEP 1c partial-coverage split).

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/test_suite/test_03_permits.py` — `test_permit_activate_succeeds_when_utilities_confirmed`, `test_occ_permit_renewal_stale_version_rejected`, `test_default_clock_value_before_any_set`: converted 6 exact-string timestamp equalities to `assert_iso8601_instant` (format was not uniquely derivable; instants are PRD-pinned).
- `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/test_suite/test_05_dust_posture_diversion.py` — `test_dust_threshold_exactly_75_is_exceedance`: changed just-below input from `measured_value=93.749` (score 74.9992) to `93.625` (score exactly 74.9); the old assertion demanded a 4-decimal `exposure_score`, contradicting PRD §2.5/§3.8 "reported to one decimal place". `test_dust_threshold_just_above_75_stops_project`: changed input from `93.751` (75.0008) to `93.875` (exactly 75.1), including the cumulative assertion. Boundary semantics (74.9 below → no exceedance; exactly 75.0 → exceedance; 75.1 above → STOPPED) are preserved with values exactly representable in the 1-decimal regime, so the tests hold under every faithful reading of the rounding rule. `test_dust_log_is_immutable_event_entity`: `recorded_at` converted to instant comparison.
- `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/test_suite/test_07_notifications.py` — `test_quiet_hours_delivery_occupation_window`: 2 `delivered_at` exact-string equalities converted to instant comparison.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/workspace/implementation/routes/projects.py` — added `ERR_BACKFILL_NOT_APPROVED` to the `from errors import (...)` list. The constant was defined in `errors.py` and used at line 133 in the START_BACKFILL gate but never imported, so the no-approved-plan branch raised `NameError` → Flask 500 HTML page → client-side `JSONDecodeError` (the only test exercising that branch was `test_start_backfill_without_approved_plan_rejected`; all other START_BACKFILL callers had an approved plan and never reached the raise). PRD §3.8 verbatim-covers the rule ("requires that at least one backfill plan of the project has reached `APPROVED` or beyond ... else `ERR_BACKFILL_NOT_APPROVED`"); the test was faithful.

## Step 8: Finalize PRD — 2026-08-15T08:53:03.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/workspace/PRD_FINALIZED.md` written. Two inline revisions, nothing else.

**Line counts / delta:** PRD.md 339 lines, PRD_FINALIZED.md 339 lines — 0.0% line-count delta; 2 lines revised in place, 0 inserted, 0 deleted.

**Changes (one bullet each):**
- §2.4 — revise — appended one sentence pinning that every timestamp the API emits (stamped fields, derived instants such as `expires_at`, and the `current_utc` echo) uses the same ISO 8601 UTC three-fractional-digit form as `created_at`/`updated_at`, rendered like `2026-08-01T00:00:00.000Z` — `implementation/util.py:17-22` (`fmt_ts`), call sites `serializers.py:27-236` (all entity timestamps incl. `activated_at`/`expires_at`/`delivered_at`/`recorded_at`), `response.py:22`, `routes/clock.py:22`.
- §2.5 — revise — "A dust exposure score is reported to **one decimal place**" → "... **one decimal place** using round-half-up", pinning the rounding mode the PRD left open — `implementation/util.py:55-56` (`round1` = `ROUND_HALF_UP`), sole call site `implementation/routes/dust.py:44`.

**No edit for theme (c):** `ERR_BACKFILL_NOT_APPROVED` was a pure implementation bug (missing import in `routes/projects.py`, fixed by Step 7). The PRD already states the rule verbatim in §3.8, lists it in the §2.9 evaluation order (step 10), and pins HTTP 409 in §5 — matching `errors.py:41` and the raise at `routes/projects.py:133`. PRD left nothing open; no change made.

**Per-edit pre-edit search log:**

Edit 1 (§2.4 timestamp format):
- (a) Subject: wire serialization format of every server-emitted timestamp beyond the already-pinned `created_at`/`updated_at` (§2.4) and `api_request_timestamp` (§2.2).
- (b) Enumerated paths (grep for `fmt_ts|strftime|isoformat` across `implementation/`): `serializers.py` — all 30 timestamp call sites across all 12 serializers (`created_at`, `updated_at`, `completed_at`, `certified_at`, `disconnect_window_start/end`, `activated_at`, `expires_at`, `finalized_at`, `delivered_at`, `recorded_at`, `received_at`, `passed_at`) — every one via `fmt_ts`; `response.py:22` (`api_request_timestamp` via `fmt_ts`); `routes/clock.py:22` (`current_utc` via `fmt_ts`); `routes/notifications.py:72` (`.date().isoformat()` — internal daily-cap key, never emitted); date-string fields `scheduled_delivery_date`/`scheduled_date`/`blackout_dates` echoed verbatim (not timestamps); `app.py`/`middleware.py` emit nothing. `fmt_ts` unconditionally emits exactly three fractional digits, so the universal claim is true on every path.
- (c) Wording adjustment: scoped to "every timestamp the API emits" with explicit mention of `expires_at` and the `current_utc` echo (the two non-"stamped" emissions), and keyed the example to the PRD's own startup instant so the existing `2026-08-01T00:00:00Z` startup sentence remains an instant statement, not a serialization claim. YYYY-MM-DD date strings excluded by the word "timestamp".

Edit 2 (§2.5 dust score rounding mode):
- (a) Subject: rounding mode of the dust exposure score only.
- (b) Enumerated paths: `routes/dust.py:43-45` (sole score computation — `round1(min(raw, 1000)/10)`, `is_exceedance` compares the rounded score to `Decimal("75.0")`); `routes/dust.py:63` (`cumulative_exposure_score` accumulates the rounded score, matching §3.8 "adds its score"); `util.py:55-56` (`round1` definition; grep confirms `dust.py:44` is its only call site); `services.py:158-166` (wind multipliers are exact Decimals, unrounded); `round4` sites (`services.py:148`, `routes/backfill.py:93,111`) are 4-decimal and untouched; compaction percentages stored unrounded and not implicated.
- (c) Wording adjustment: mirrored the adjacent sentence's existing "using round-half-up" phrasing; kept scope strictly on "a dust exposure score" so no other numeric field is newly constrained. §3.8's restatement "reported to one decimal place" was left verbatim — it stays true and defers to §2.5 for mode.

Note on test-side evidence: the converted assertions cover `activated_at`, `expires_at` (test_03:224-225, 262, 272, 399-400), `recorded_at` (test_05:177), and `delivered_at` (test_07:75, 81) — all inside the set Edit 1 now pins; the dust boundary fixtures (93.625 → 74.9; 93.875 → 75.1) are exact in the 1-decimal regime and hold under the now-pinned half-up rule.

## Step 9: Complete PRD — 2026-08-15T09:15:42.000Z

Done. All edits applied to `/home/ubuntu/github/CodingPRD/tasks/task_1996_demolition_contracting_salvage/workspace/PRD_COMPLETED.md` (created via `cp` from `PRD_FINALIZED.md`, then edited in place).

**Stats**
- Source: `PRD_FINALIZED.md` — 339 lines, 55,280 chars. Output: `PRD_COMPLETED.md` — 341 lines, 59,185 chars. Delta: +2 lines, +3,905 chars (all in-paragraph inserts/revisions; no new sections).
- Counts: 15 ambiguity-pins, 6 mismatch-revisions (21 changes total).

**Change log**
- §2.2 success envelope — insert — ambiguity — `api_request_timestamp` is wall-clock UTC, not the logical clock — implementation/response.py:22
- §2.2 error envelope — insert — ambiguity — undeclared paths return the standard envelope with `ERR_NOT_FOUND` (404); an undeclared method on an existing path gets a bare framework 405 outside the envelope — implementation/app.py:50-52
- §2.3 pagination — insert — ambiguity — out-of-range `limit`/`offset` are clamped (not rejected); non-numeric values → `ERR_VALIDATION`; `created_at` ties broken by creation order — implementation/response.py:48-65
- §2.4 logical clock — revise — ambiguity — expiry sweep runs on every request to any `/demolition` endpoint, not only permit/project reads — implementation/app.py:37-42
- §2.4 clock setter — insert — ambiguity — `to_iso8601` must be timezone-aware (naive/malformed → `ERR_VALIDATION`); any instant accepted, including earlier than current time — implementation/routes/clock.py:16-19, implementation/util.py:25-38
- §2.9 step 2 — insert — ambiguity — per-action role restrictions are evaluated after path resolution and before state legality, surfacing `ERR_FORBIDDEN` — implementation/routes/permits.py:80-81, surveys.py:165-166, engineering.py:71-72, backfill.py:86-87
- §2.9 step 3 — insert — ambiguity — body must be a JSON object (non-object → `ERR_VALIDATION`; absent/unparsable → treated as empty); unused fields ignored; action-conditional required fields enforced after state legality — implementation/middleware.py:53-61, tickets.py:94-100, backfill.py:96-100, inspections.py:97-101
- §2.9 step 5 — revise — ambiguity — enumerates the posture-gated writes: release, the four phase transitions, debris-ticket creation, and no others — implementation/routes/projects.py:117-154, tickets.py:38-39
- §3.1 project list — insert — ambiguity — `status` and `pinned_engineering_survey_id` filters may combine (AND semantics) — implementation/routes/projects.py:74-79
- §3.1 survey lifecycle — insert — ambiguity — survey born with `hazmat_found` false and `findings_summary` empty; COMPLETE's two fields are optional, omitted values persist — implementation/routes/surveys.py:43-52, 94-100
- §3.2 abatement creation — insert — ambiguity — opening an order is not gated on survey status or `hazmat_found` — implementation/routes/surveys.py:127-146
- §3.3 utility verification — insert — ambiguity — REJECT_VERIFICATION keeps `verified_by_user_id`; re-verification re-records it — implementation/routes/utilities.py:85-90
- §3.3 permit creation — insert — ambiguity — permit born `DRAFT` with `revision_count` 0 and `renewal_count` 0 — implementation/routes/permits.py:55-57
- §3.4 engineering survey — revise — ambiguity — `adjacent_structure_distance_ft` pinned as an integer zero or greater — implementation/routes/engineering.py:36
- §3.5 manifest creation — insert — ambiguity — born with both totals and `net_credit_cents` at zero, `amendment_count` 0; `quantity` is an integer; adding to `FINALIZED` → `ERR_INVALID_STATE` — implementation/routes/salvage.py:53-64, 94-104
- §3.5 totals — revise — mismatch — "optimistic strictly greater whenever any high exceeds low" fails under negative amendment quantities; restated per-line with sign-flip note — implementation/routes/salvage.py:30-32
- §3.5 net-credit invariant — revise — mismatch — invariant "at all times" false in `DRAFT` (net reads 0 while fee/items exist); pinned to hold from first finalization, with per-add recompute while `AMENDED` — implementation/routes/salvage.py:41-42, 122-126
- §3.7 release step 6 — revise — mismatch — `VOIDED` notifications tolerated: release needs ≥1 notification, none `PENDING_DELIVERY`, ≥1 `DELIVERED` (was "all must be DELIVERED") — implementation/routes/projects.py:172-176
- §3.8 resume — revise — mismatch — resume defined for any `STOPPED` project including `FINAL_REVIEW` (was limited to three phases) — implementation/routes/projects.py:189-198
- §3.8 ticket receipt — revise — mismatch — negative/over-precise `diverted_tons` → `ERR_VALIDATION` (not `ERR_TICKET_WEIGHT_INVALID`); only exceeding `gross_tons` draws the latter — implementation/routes/tickets.py:82, 99-100; also pinned new-ticket zeros and the same negative-input split for RECONCILE's corrected figures (zero corrected gross permitted) — implementation/routes/tickets.py:84-88, 124-129
- §3.9 backfill/closure — insert — ambiguity — plan born with zero ratios and unset measured/achieved fields; `required_compaction_pct` > 0; measured areas are integers (disturbed positive, protected non-negative); inspection born with `attempt_count` 0 / empty `inspector_note`, and only FAIL increments it; RESCHEDULE does not re-run the one-outstanding check — implementation/routes/backfill.py:37-55, 79-83; implementation/routes/inspections.py:36-45, 97-103

Everything else in the implementation (endpoint/role matrix, per-action role maps, all state machines, fee/exposure/diversion/coverage formulas, cascade contents, OCC guards, error-id/HTTP-status catalogue, envelope shape) matched the PRD as written and was left untouched.
