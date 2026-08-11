# Worklog — task_1178_retail_construction_rollout_program

## Step 1: Create Task Directory — 2026-08-11T11:09:14.411Z

Pre-assigned output folder `tasks/task_1178_retail_construction_rollout_program` with `workspace/` subdirectory already exists; auto-index scan skipped per instruction. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-11T12:06:37.780Z

All three scaffold artifacts are generated, lint-clean, and saved under `/home/ubuntu/github/CodingPRD/tasks/task_1178_retail_construction_rollout_program/`.

## Counts

| Artifact | Contents |
|---|---|
| `SCAFFOLD.yaml` | 14 entities, 13 state machines, 8 calculations, 12 ordered validation rows, 3 OCC concurrency rules, 82 endpoints, 41 error codes, 8 roles |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 19 instances — every one of the 9 rules at ≥2, with `combinatorial_formula` at 3 (one per mode a/b/c) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 63 instances across all 9 guide sections (59 full recipes + 4 `excluded_because` stubs) |

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (1,663 calls scanned). Every error code has at least one triggering instance; zero dangling `grounds` references; zero unbound `${var}` placeholders; all instance names unique across the union of both design files.

## Design decisions worth recording

- **Archetype mix**: workflow_orchestration + compliance_audit; flat topology (all FKs via filtered-list GETs), segregation_of_duties role model (CO proposer ≠ approver), immediate consistency. Layers: OCC, cascading side effects, dual-variant calculation, version-pinning on approval.
- **Two denominator trap**: variance ratios are computed against `base_contract_cents` (contract overrun) while approval headroom is checked against `budget_allocation_cents` (budget envelope) — two plausible "budget variance" readings that diverge.
- **Dual-variant anchors**: site variance final-vs-provisional (444bp vs 578bp on identical data), bid evaluation LOWEST_PRICE vs BEST_VALUE (identical bid tuples crown different winners, scores 88.00 vs 95.88 precomputed), forecast optimistic-vs-conservative.
- **Pinned circular evaluation order** for `opening_date_forecast`: budget ratios → slip factor → forecast → protection posture; the 1-day delta between conservative (2026-09-05) and optimistic (2026-09-04) makes the ordering observable.
- **Rounding pinned per-permit-then-sum** for permit fees (110,126 vs 110,125 cents — a 1-cent discriminator), refile at exactly half fee, and **exact rational (unrounded) tier comparison** for change-order tiers so 200,000 vs 200,001 cents on a 10,000,000 base flips STANDARD→ELEVATED.
- **Two interval semantics** for temporal-overlap: pairwise half-open windows with adjacency allowed on Site, vs aggregate per-day crew capacity (`concurrent+1 <= max`, at-capacity allowed) on Market.
- **Cascade depth-3 chains** spelled per-hop in side_effects: CO approve → site ledger → site posture → program reserve/posture; vendor complete → readiness → site auto-PUNCH → protection-posture recovery (AT_RISK→PROTECTED with literal dates).
- **Deterministic time**: logical clock endpoint with startup default 2026-05-01T00:00:00Z; permit expiry only via `POST /rollout/_sweeps/time-based`, never lazy wall-clock.
- **OCC on Site.version** guards PATCH site, CO approve, and turnover accept; every `expected_site_version` in recipes is a `${var}` capture, and failed validation attempts never bump the version (asserted explicitly in the tier-authority instance).
- Grand-opening protection is enforced two ways: `ERR_OPEN_DATE_LOCKED` (past-DESIGN date edits need a director override reason) and `ERR_OPENING_LOCK_ENGAGED` (SCHEDULE-category COs blocked at AT_RISK/BREACHED while SCOPE COs still approve).

## Step 3: Copy Shared Files — 2026-08-11T12:06:58.835Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1178_retail_construction_rollout_program/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-11T12:22:57.567Z

Generation complete. Summary of what was produced:

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1178_retail_construction_rollout_program/workspace/PRD.md` — 386 lines.

**Section list**
- §1 Introduction (2 paragraphs — business context + system scope, `/rollout` mount)
- §2 Global Specifications: 2.1 RBAC (8 roles, header names, identity prose per role — `GCVendor` entity-backed to `Contractor`, seven opaque roles), 2.2 API Response Structure (byte-identical verbatim block, verified by diff), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, four meta fields), 2.4 Common Resource Properties and Versioning, 2.5 Logical Clock and Time-Based Sweep (startup default 2026-05-01T00:00:00Z, `to_iso8601`/`current_utc`, sweep outputs), 2.6 Units/Precision/Rounding, 2.7 OCC (3 rules, `expected_site_version`, `ERR_STALE_VERSION` 412, stale-read framing), 2.8 Hierarchical Consistency and Automatic Reconciliation, 2.9 Nested Resource Retrieval, 2.10 Validation Evaluation Order (all 12 priorities in prose with error IDs)
- §3 Business Logic (8 subsections, chronological lifecycle): 3.1 Program/Market/Site setup incl. PATCH lock + removal cascade asymmetry; 3.2 Drawing sets and jurisdiction variances; 3.3 Permitting (fee schedule, ledger rounding order, refile loop, mark-permitted two-tier gate); 3.4 GC bidding and award (both evaluation modes, full award cascade); 3.5 Vendor sequencing (5 scheduling checks, readiness derivation, auto `PUNCH`); 3.6 Change orders and budget variance (tier, six approval gates in global priority order, all four outcomes, both variance ratios, program rollup with 25%/100% reserve terms); 3.7 Punch list, turnover, store opening; 3.8 Grand-opening date protection (pinned evaluation order, slip factor, optimistic/conservative blocks and vendor chain, 10-day buffer, all posture bands incl. `BREACHED` recovery)
- §4 Endpoint Definitions — 82 rows, 4 columns only
- §5 Error Code Catalogue — 41 rows, 2 columns only

**Hard contract results**
- Contract 1 (field names): 84/84 entity fields, 56/56 endpoint input+query identifiers, 13/13 path params present in backticks — PASS (initial run's false alarm traced to naive backtick pairing across the §2.2 code fences; re-ran with fenced blocks stripped)
- Contract 2 (rules): all 13 state machines' transitions (incl. cyclic loops and the deliberate remove-cascade asymmetry: mobilization cancellation only from `LISTED`/`IN_BUILD`/`PUNCH`/`TURNOVER`), all 8 calculations with constants/variants/precision in reconstructible prose, all 12 validation priorities with applies_to scopes, all 3 OCC rules, endpoint side effects, field defaults/nullability, 16 `OpeningCommitment` posture transitions via band rules — PASS
- Contract 3 (§3 purity): 570 backticked tokens scanned, 0 path/method violations — PASS
- Aux checks: 41/41 error IDs in §2/§3 prose, 8/8 roles, 44/44 states (one fix applied: `RESCINDED` added to §3.6), 69/69 enum values; §2.2 verbatim match byte-identical; document ends at §5 with no audit footer.

**Decisions worth recording**
- §2 organized into 10 subsections with domain titles (clock/sweep and validation-order got their own subsections since the scaffold is time- and priority-driven).
- §3 grouped chronologically by rollout phase (8 subsections) rather than by role or entity.
- The 16 enumerated `OpeningCommitment` transitions were rendered as compact slip-band rules plus the director-override recovery and `MET`-on-open rules, preserving every band boundary (0 / 1–7 / 8–21 / 22+) exactly.
- The withheld index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced; the PRD was derived solely from `SCAFFOLD.yaml`, the skill spec, the §2.2 source, and the style example.

## Step 5: Generate Unit Tests — 2026-08-11T12:57:35.737Z

All done. Summary of the generation:

## Files generated

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1178_retail_construction_rollout_program/test_helpers/`):
- `types.py` — 14 entity TypedDicts (all carry id/created_at/updated_at/version per PRD common-properties), 20 status/enum classes, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with 86 methods, one per PRD endpoint, incl. clock/sweep and PATCH site
- `api_errors.py` — `ApiErrorId` (41 errors) + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_site_ledger_invariants`
- `factories.py` — 13 payload factories (input fields only)
- `constants.py` — clock default, punch buffer, tier/posture/slip thresholds, bid weights, scenario defaults
- `test_users.py` — `TEST_USERS` for all 8 roles + `make_*_headers` builders (GCVendor entity-backed by Contractor; per-instance builders used for all ownership-gated calls)
- `fixtures.py` — ~45 primitive steps + composite builders: `setup_site_in_design/permitting/mobilized`, `setup_awarded_site`, `setup_site_in_build/punch/turnover/open`, `setup_multi_sites_in_build`, `complete_vendor_window`, `approve_change_order_now` (fresh-version OCC), `accept_turnover_now`, `read_commitment_for_site`; all setup via `get_success_data`
- `__init__.py` — barrel export (framework + PRD-specific)

**`test_suite/`** (12 files): `conftest.py` + `test_01_program_market_setup` (4), `test_02_site_creation_and_update` (10), `test_03_drawing_pipeline` (5), `test_04_permits` (13), `test_05_bidding_and_award` (15), `test_06_vendor_mobilization` (13), `test_07_change_order_gates` (13), `test_08_budget_cascades` (6), `test_09_punch_turnover` (12), `test_10_opening_forecast` (3), `test_11_variance_dual_variant` (2).

## Coverage
- **Total tests: 96** (collected cleanly by pytest against the framework).
- **Queue A (Difficulty): 19/19 instances, exactly 2 tests each = 38 tests.** Second tests target a distinct facet of the same rule (isolated single-failure variants for the two priority-pair instances, 500bp slip-factor boundary, readiness ladder, left-edge adjacency, disjoint-day capacity, completion-frees-capacity, partial rescind compensation, two-site OVERRUN aggregation, double-reopen loop, half-fee-again refile, posture convergence after approval, null-score/loser-status under LOWEST_PRICE, filtered-min proof via the 88.00 score, jurisdiction/permit-type mismatch).
- **Queue B (Corner): 58/59 non-stub instances, 1 test each.** All 4 `excluded_because` stubs correctly untranslated (cross-references resolve to real difficulty instances).

## Skipped instances
- **`Corner/state_machines/c_bid_withdraw_after_award_terminal`** — PRD-contradicted: §3.4 explicitly names the error for this scenario ("only while the package is not yet `AWARDED` (`ERR_INVALID_STATE` once it is)"), while the instance asserts `ERR_ALREADY_TERMINAL`. A PRD-faithful implementation would emit `ERR_INVALID_STATE`, so the asserted outcome is not PRD-derivable. Gap left as a gap.

## Decisions worth recording
1. **Version-anchor relaxation**: PRD §2.4 pins "increments with every mutation" but never the counter's initial value, so (a) `c_version_increments_on_each_mutation` asserts relative +1-per-transition instead of the recipe's absolute 1/3 anchors, and (b) the `version == 1` assertion was dropped from `c_program_create_applies_defaults` (all other defaults asserted).
2. **`evaluation_score`** asserted via `pytest.approx(x, abs=0.005)` — pins the exact 2-decimal value while tolerating JSON float round-trip.
3. **PRD citation audit passed**: all 129 quoted spans across 96 docstrings survive whitespace-normalized literal match against PRD.md; every test carries exactly one `Design:` tag resolving to a real instance; no skip/xfail markers; no scaffold references in comments.

## Step 6: Generate Implementation — 2026-08-11T12:57:35.737Z

Implementation complete and verified. Summary follows.

## Implementation Summary — task_1178_retail_construction_rollout_program

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1178_retail_construction_rollout_program/workspace/implementation/`)

- `start.sh` — executable launcher (see below)
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask app factory, error handlers (ApiError / 404 / 405 / 500), `app.run(host="0.0.0.0", port=$PORT or 10000, threaded=True)`
- `clock.py` — logical clock, default `2026-05-01T00:00:00Z`; wall clock never consulted (used for `created_at`/`updated_at`/`submitted_at`/`filed_at`/`issued_at`/`actual_*_on` and envelope `api_request_timestamp`)
- `db.py` — empty-at-boot in-memory store (14 dicts + monotonic sequence; no seeding anywhere)
- `errors.py`, `response.py`, `middleware.py`, `validate.py`, `util.py` — envelope (`meta`/`response_type`/`data`, error body `error_id`/`message`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, range 1..100), auth (`X-User-ID`/`X-User-Role`, 8 roles), shape validators, request-scoped bump coalescing
- `routes/` — `admin.py` (clock, sweep), `programs.py`, `markets.py`, `municipalities.py`, `sites.py`, `drawings.py`, `permits.py`, `contractors.py`, `bid_packages.py`, `bids.py`, `mobilizations.py`, `change_orders.py`, `punch_items.py`, `turnovers.py`, `commitments.py`
- `services/` — `budget.py` (site variance, program rollup, punch counts, readiness), `forecast.py` (opening_date_forecast, slip factor, protection posture)

### Coverage
All 82 endpoints from the endpoint table are implemented (route-pair parity with SCAFFOLD.yaml verified by orchestrator: 82/82, 0 missing, 0 extra). All 14 entities, all state machines (including cyclic loops: drawing revise, permit refile, punch fail-verification, posture bands both directions, TURNOVER→PUNCH revert), all 8 calculations, all 40 error IDs with their exact HTTP statuses, and validation priority order §2.10 (auth → role → identity → existence → state → OCC → compliance → cross-entity → temporal → uniqueness/capacity → fiscal → shape).

### Key mechanics
- **OCC**: `expected_site_version` on PATCH site / CO approve / turnover accept → 412 `ERR_STALE_VERSION`; missing/malformed defers to step-12 `ERR_INVALID_REQUEST`. OCC checked before tier/SoD/lock/headroom on approve.
- **Versioning (§2.4)**: `version` starts at 1; request-scoped bump registry guarantees exactly one increment per mutated resource per request even across multi-step cascades; pure recomputes bump only on actual value change.
- **Calculations**: all money integer cents via `Decimal`/`ROUND_HALF_UP`; permit fee per-permit rounding pinned before ledger summation (refile = round_half_up(0.5 × base)); CO tier by exact rational comparison (`abs(amount)*10000 <= 200/500 * base`, no rounding); BEST_VALUE score `0.7*(min/amount)*100 + 0.3*tech` at 2dp half-up; forecast evaluation order pinned (ratios → provisional slip factor 0/500/1500 → dates → posture); conservative vendor durations padded by slip factor with half-up day rounding; ON_SITE mobilizations count remaining time only; PUNCH_BUFFER_DAYS = 10.
- **Cascades**: award (winner/loser bids, market BIDDING→AWARDED, base contracts on matching wave sites, rollups + forecasts); site removal (state-dependent mobilization cancellation per PRD: LISTED/IN_BUILD/PUNCH/TURNOVER cancel PLANNED/SCHEDULED, DESIGN/PERMITTING/MOBILIZED do not; PROPOSED COs→REJECTED; REQUESTED turnover→SUPERSEDED; rollup exclusion); CO approve/rescind compensation; turnover accept (minor-waiver sweep, actuals = committed, program actuals).

### start.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
```

### Boot smoke-check results
- `bash start.sh` boots in ~2s (guard skips pip when flask present), binds 0.0.0.0:$PORT, foreground via `exec`; fresh reboot verified pristine (empty store, clock reset to 2026-05-01T00:00:00Z) — satisfies per-test-server isolation.
- Four end-to-end scenarios (~180 assertions) all pass: auth/RBAC, program/market/site setup, OCC on PATCH (412) and open-date lock + director override, drawing revision/supersede/revise loop, permit fee math (7000, 12625, refile half-fee 6313), ledger debit/refund, `ERR_DRAWING_SUPERSEDED`, `ERR_PERMIT_EXPIRED` (both pre- and post-sweep), BEST_VALUE scoring (88.0 vs 91.5 wins despite higher price, scores frozen at award) and LOWEST_PRICE nulls, duplicate/identity/suspension/window bid gates, vendor predecessor/overlap/capacity (cap 2: third concurrent crew → `ERR_MARKET_CAPACITY_FULL`, release on cancel), auto PUNCH + SIGNAGE_HUNG, punch rework loop, turnover gates (critical-open, minors outstanding, stale 412, waive sweep), accept→actuals, open→MET, removal cascades, program rollup (WITHIN_PLAN→GUARDED at reserve 250000/pool 300000→OVERRUN at free −1700000), slip-band posture migration (PROTECTED↔WATCH/AT_RISK/BREACHED via PATCH and sweep), tier boundaries (200bp STANDARD, 500bp ELEVATED, 501bp CRITICAL), SoD/tier-authority 403s, OCC-before-headroom ordering, pagination meta and limit range 400s.

### Decisions worth recording (ambiguous points resolved toward the PRD's literal text)
1. **Commitment at site creation**: forecasts/slip computed by the algorithm, but `protection_posture` forced to `PROTECTED` per §3.1's declarative "its posture reading PROTECTED" + state-machine initial_state.
2. **Turnover accept punch gate**: literal reading — CRITICAL/MAJOR must be `VERIFIED` (a `WAIVED` MAJOR still blocks); MINOR need VERIFIED/WAIVED or `waive_open_minor`.
3. **CO approve on terminal site** → `ERR_ALREADY_TERMINAL` (both OPEN and REMOVED are terminal per §3.6's "or ERR_ALREADY_TERMINAL for a terminal site"); **rescind** on OPEN/REMOVED site → `ERR_INVALID_STATE` (PRD's rescind text).
4. **Tier authority is strict**: STANDARD/ELEVATED → FinanceController only, CRITICAL → ProgramDirector only (a ProgramDirector approving STANDARD gets `ERR_CO_TIER_ROLE_REQUIRED`).
5. **Uniqueness without a catalogued error** (duplicate `municipality_code`, duplicate `license_no`) → `ERR_INVALID_REQUEST` 400.
6. **Bid `evaluation_score`**: computed live for BEST_VALUE packages pre-award (min over current SUBMITTED-responsive candidate set), frozen onto candidates at award; null under LOWEST_PRICE and for non-responsive/withdrawn bids.
7. **Permit ledger mutations** (file/refile/withdraw) bump the site's `version` per §2.4's "any change to stored state" rule.
8. **Sweep** skips commitments whose site is OPEN/REMOVED (forecast input set excludes them) and commitments already MET; `recomputed_commitment_ids` lists every processed commitment.
9. **`limit`/`offset` outside 1..100 / <0** → `ERR_INVALID_REQUEST` 400 rather than clamping.

### Orchestrator route-parity check (pre-Step 7)
Normalized (method, path) comparison of SCAFFOLD.yaml `endpoints:` (82) vs Flask `@*.route` registrations in `workspace/implementation/` (82): 0 missing, 0 extra — parity confirmed before sweeping.

## Step 7: Test–Fix Loop (8-round stability sweeps) — 2026-08-11T13:20Z

Three sweep iterations run; final sweep clean: all 8 parallel rounds 96/96 passed, 0 failed, 0 errors.

- **Iteration 1**: 65/96 per round (31 deterministic failures, 8/8 rounds each). Root causes: (a) `test_helpers/api_client.py::start_site_build` f-string referenced undefined `{siteId}` (NameError) — broke every setup chain containing start-build (30 tests); (b) `test_07::test_headroom_exact_boundary_approve_succeeds_plus_one_fails` approved a 1-cent STANDARD-tier CO as ProgramDirector, tripping step-7 tier authority before the step-11 headroom check.
- **Iteration 2**: 94/96 per round. Two remaining deterministic failures: (a) `test_06::test_same_site_vendor_window_half_open_overlap` fixture bug — rejected fix2 stayed PLANNED and overlapped fix3 (PRD §3.5 counts PLANNED windows as blockers), so the PRD-faithful implementation correctly rejected fix3; (b) `test_09::test_second_turnover_request_rejected` — ERROR PRECEDENCE SILENCE between two step-5 guards (ERR_INVALID_STATE vs ERR_TURNOVER_ALREADY_REQUESTED), relaxed to `validate_error_is_one_of` per protocol.
- **Iteration 3**: clean — 8/8 rounds at 96/96.

Fixes applied (no test deletions; no implementation changes were needed):
1. `test_helpers/api_client.py` — `start_site_build`: fixed f-string path interpolation `{siteId}` → `{site_id}`.
2. `test_suite/test_07_change_order_gates.py` — headroom boundary test: approve the STANDARD-tier 1-cent CO as FinanceController (tier authority, §3.6) so the fiscal headroom gate is what fires.
3. `test_suite/test_06_vendor_mobilization.py` — half-open overlap test: narrowed fix2 window to [06-15, 06-21) so it still overlaps fix1 (rejected) but only touches fix3 at the boundary.
4. `test_suite/test_09_punch_turnover.py` — second-turnover test: relaxed exact error to `validate_error_is_one_of([ERR_TURNOVER_ALREADY_REQUESTED, ERR_INVALID_STATE])`; added post-condition that the site remains TURNOVER.

## Step 8: Finalize PRD — 2026-08-11T13:17:05.372Z

Done. `PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1178_retail_construction_rollout_program/workspace/PRD_FINALIZED.md` with exactly one pinned line.

## Line counts and delta
- `PRD.md`: 386 lines; `PRD_FINALIZED.md`: 386 lines — 0.0% line-count delta; 1 line revised (line 227, +144 chars).

## Changes
- **§3.7 (turnover-request paragraph, line 227) — revise** — reordered the three turnover-request guards to the implementation's evaluation order (site-in-`PUNCH` → no outstanding `REQUESTED` turnover → zero open criticals) and pinned that order plus its observable consequence: a second request after the first already moved the site to `TURNOVER` is rejected with `ERR_INVALID_STATE` — impl: `implementation/routes/turnovers.py:26-39` (`invalid_state` at :27, `ERR_TURNOVER_ALREADY_REQUESTED` at :34, `ERR_PUNCH_CRITICAL_OPEN` at :38).

## Step_7_diff items evaluated, no edit needed
1. **`test_helpers/api_client.py::start_site_build` f-string** — pure helper bug. PRD §4 already pins `POST /rollout/sites/{siteId}/start-build`; impl `routes/sites.py:216` matches. No PRD silence.
2. **`test_07` headroom-boundary role fix** — pure fixture bug. PRD §2.10 already pins tier authority (step 7) before fiscal headroom (step 11), and §3.6 pins FinanceController for STANDARD/ELEVATED; impl `routes/change_orders.py:103-114` (tier authority) before :126-130 (headroom) matches, as does the exact-boundary-passes semantics (`>` at :128 vs PRD "not exceeding"). No PRD silence.
3. **`test_06` half-open overlap narrowing** — pure fixture bug. PRD §3.5 already pins `PLANNED`/`SCHEDULED`/`ON_SITE` as overlap blockers under half-open semantics, and a rejected schedule leaving the mobilization `PLANNED` follows from the from-state spec plus rejection-non-mutation; impl `routes/mobilizations.py:99-111` matches. No PRD silence.
4. **`test_09` second-turnover precedence** — the one genuine PRD silence (§2.10 step 5 lists both guards without pinning intra-step order); fixed by the edit above.

## Per-edit pre-edit search log
- **(a) Subject**: guard evaluation order within `POST /rollout/turnovers` — precedence among `ERR_INVALID_STATE` (site not `PUNCH`), `ERR_TURNOVER_ALREADY_REQUESTED`, and `ERR_PUNCH_CRITICAL_OPEN`.
- **(b) Impl paths enumerated and read/grepped**: `routes/turnovers.py:20-60` `create_turnover` (repo-wide grep confirms it is the *sole* raise site of `ERR_TURNOVER_ALREADY_REQUESTED` and `ERR_PUNCH_CRITICAL_OPEN`; order: `invalid_state` :27 → already-requested :29-35 → critical-open :36-39); `routes/__init__.py:9-16` `require_state` (generic from-state guard on other endpoints, untouched by this edit); `errors.py:37-38` (`ERR_INVALID_STATE` → 409, matches §5); `routes/sites.py:250-285` removal cascade superseding `REQUESTED` turnovers; `routes/sites.py:229-247` open requiring `ACCEPTED`; `routes/turnovers.py:133-147` reject reverting `TURNOVER`→`PUNCH` — none of these re-evaluate the creation guards. Cross-checked §2.10: `ERR_INVALID_STATE` and `ERR_TURNOVER_ALREADY_REQUESTED` are both step-5 (intra-step order unpinned globally, so a local pin does not contradict), `ERR_PUNCH_CRITICAL_OPEN` is step-10 (after both — consistent with the new wording).
- **(c) Wording adjustment**: the guard list was reordered to the impl's evaluation order — the PRD previously listed critical-open *before* already-requested, which also sat oddly against §2.10's step ordering — and the pin was scoped strictly to the turnover-request operation ("the three guards are evaluated in that order") with the concrete second-request consequence stated. Every enumerated path is consistent with the new sentence; no off-site behavior is narrowed, reordered, or excluded.

## Step 9: Complete PRD — 2026-08-11T13:28:36.859Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1178_retail_construction_rollout_program/workspace/PRD_COMPLETED.md` is produced (copied from `PRD_FINALIZED.md`, then edited in place only).

## Summary

**Source vs output:** `PRD_FINALIZED.md` 386 lines / 52,189 chars → `PRD_COMPLETED.md` 386 lines / 54,405 chars (char-delta **+2,195**; line count unchanged — all changes are in-paragraph inserts/revisions, no new sections).

**Counts:** 13 ambiguity-pins (inserts), 6 mismatch-revisions.

**Changes:**

- §2.3 — insert — ambiguity — malformed pagination params (non-integer limit/offset, limit outside 1..100, negative offset) pinned to `ERR_INVALID_REQUEST` — implementation/response.py:42-64
- §2.3 — insert — ambiguity — list ordering ties on identical `created_at` break by creation sequence — implementation/util.py:105-106, routes/__init__.py:38
- §2.3 — insert — ambiguity — `has_more` defined as `offset + returned < total_count`; filters pinned as exact-match with `ERR_INVALID_REQUEST` for unparseable integer filters — implementation/response.py:28, routes/__init__.py:19-34
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — implementation/util.py:56-65
- §2.4 — insert — ambiguity — one `version` increment per resource per request regardless of cascade count; a no-change recomputation is not a mutation (no bump, no `updated_at` refresh) — implementation/util.py:68-98
- §2.5 — insert — ambiguity — clock setter accepts any parseable instant (backward allowed, no monotonicity); `current_utc` returned at whole-second precision — implementation/clock.py:32-37, routes/admin.py:17-25
- §2.5 — insert — ambiguity — sweep's "non-terminal commitment" defined: `MET` commitments and commitments of `OPEN`/`REMOVED` sites are skipped — implementation/routes/admin.py:42-49
- §2.10 — revise — mismatch — step 7 intra-order pinned to tier-authority-then-segregation (was listed segregation-first) — implementation/routes/change_orders.py:103-114
- §3.3 — insert — ambiguity — duplicate `municipality_code` at profile registration → `ERR_INVALID_REQUEST` — implementation/routes/municipalities.py:32-33
- §3.4 — insert — ambiguity — duplicate `license_no` at contractor registration → `ERR_INVALID_REQUEST` — implementation/routes/contractors.py:24-25
- §3.4 — revise — mismatch — bid withdrawal after award yields `ERR_ALREADY_TERMINAL` (award cascade already moved the bid to terminal `AWARDED`/`REJECTED`), not `ERR_INVALID_STATE` — implementation/routes/bids.py:16,108-118
- §3.4 — insert — ambiguity — pre-award live `evaluation_score` display under `BEST_VALUE` (null for non-responsive/non-SUBMITTED and all `LOWEST_PRICE` bids), frozen against the award-time candidate set at award; rankings tied after `submitted_at` break by creation order — implementation/routes/bids.py:19-24, routes/bid_packages.py:42-62,151-158
- §3.6 — revise — mismatch — proposal gate: dropped the unenforced "site in its building phase" requirement; only the market-`AWARDED` gate exists — implementation/routes/change_orders.py:37-51
- §3.6 — revise — mismatch — tier rule: removed the false "safe because proposal only happens after a positive base contract" claim; pinned the zero-base rule (amount 0 → `STANDARD`, nonzero → `CRITICAL`) — implementation/routes/change_orders.py:23-32
- §3.6 — revise — mismatch — approval site gate on `OPEN`/`REMOVED` is always `ERR_ALREADY_TERMINAL` (was "ERR_INVALID_STATE, or ERR_ALREADY_TERMINAL") — implementation/routes/change_orders.py:91-95
- §3.7 — insert — ambiguity — punch-item creation outside `PUNCH`/`TURNOVER` → `ERR_INVALID_STATE` — implementation/routes/punch_items.py:25-27
- §3.8 — revise — mismatch — recomputation trigger list now includes the §3.4 award cascade (previously omitted though §3.4 and impl recompute forecasts at award) — implementation/routes/bid_packages.py:176-189
- §3.8 — insert — ambiguity — refiling and withdrawing a permit do not fire recomputation; recomputation never touches a `REMOVED` site's commitment — implementation/routes/permits.py:193-234, services/forecast.py:109-118

Deliberately left unpinned as out of PRD scope: Flask-framework fallbacks (`ERR_INTERNAL` 500, 405 method-not-allowed) — §2.2 scopes the error contract to 4xx domain responses, and §5's catalogue maps only narrative-triggered errors.
