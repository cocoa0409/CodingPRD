# Worklog — task_1919_plastics_extrusion_profile_plant

## Step 1: Create Task Directory — 2026-08-15T00:43:00.000Z

Task directory `tasks/task_1919_plastics_extrusion_profile_plant/` and `workspace/` already existed (created by the pipeline runner). No index scan or directory creation performed by this orchestrator per instructions.

## Step 2: Generate Scaffold — 2026-08-15T01:20:52.000Z

All done. `scaffold_lint.py` verdict: **clean lint** (907 calls scanned across §1.8+§1.9; all conform to §1.5; all FKs reverse-reachable).

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts
- **Entities: 14** — Customer, Profile, Die, ExtrusionLine, ResinLot, Formulation, BlendBatch, WorkOrder, LineAssignment, ProductionRun, SPCSample, CutBundle, PurgeEvent, ResinIndexPoint (flat topology, `api_prefix: "/"`)
- **State machines: 9 blocks** — cyclic Die (TRIAL→DRAFT revert, IN_SERVICE⇄MAINTENANCE), cyclic ExtrusionLine (RUNNING→DOWN→RUNNING), cyclic ProductionRun (RUNNING⇄HOLD), quarantine/re-release loop on BlendBatch, and WorkOrder with two independent status dimensions (production × billing)
- **Calculations: 8** — incl. dual variants PER_METER/PER_KG tooling amortization and MONTHLY_AVG/SHIPMENT_DATE resin pass-through; combinatorial modes (a) purge tiers, (b) pinned nested-rounding blend/bundle, (c) pinned evaluation-order invoice total
- **Validations: 30** ordered priority rows (renumbered to integers 1–30 after catching that YAML floats collide `9.1`/`9.10`)
- **Endpoints: 50** (incl. `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- **Error catalog: 27** — every code cited by at least one §1.8/§1.9 instance
- **Roles: 5** (all `identity: opaque`; segregation_of_duties: hold release / batch re-release must come from a different inspector)
- **Concurrency rules: 3** OCC rules (reprice on WorkOrder, amortization adjustment on Die, restate on ResinIndexPoint — all 412 ERR_STALE_VERSION)
- **§1.8 instances: 21** across all 9 difficulty rules (≥2 each; cascades: SPC-OOC depth-4 and batch-quarantine depth-4 from different triggers; invariants: resin mass kg and tooling cents)
- **§1.9 instances: 47** (44 with executable recipes + 3 `excluded_because` stubs), spanning all nine claim-extraction-guide sections

All literal math in asserts was precomputed (e.g., blend 1000 kg → 38.5/100.0/861.5; invoice total 8,100,000 cents; restate cascade exposure 5,090,700; purge 6.40/19.20/13.44 kg). No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-15T01:21:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1919_plastics_extrusion_profile_plant/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T01:32:56.000Z

All verification passes. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/workspace/PRD.md`.

## Summary

**PRD line count:** 291 lines (~8,180 words)

**Sections written:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Units/Precision/Rounding, 2.7 OCC, 2.8 Validation Order and Error Precedence, 2.9 Mass Balance & Tooling Amortization Invariants, 2.10 Nested Retrieval & Code Uniqueness
- §3 Business Logic (8 subsections): customers/profiles, die tooling & amortization, materials (lots/formulations/blend batches), quoting & resin-index pass-through & credit gates, scheduling & purge gates, production runs & hold cascade, SPC & run completion, closeout invoicing
- §4 Endpoint table (50 rows, 4 columns), §5 Error catalogue (27 rows, 2 columns)

**Scaffold coverage:**
- **Entities:** all 14 covered; all 97 field names in backticks (verified mechanically)
- **State machines:** all 8 machines, all transitions with preconditions, side effects, and version bumps (all 30 state strings verified present)
- **Calculations:** all 8 expressed as step-pinned prose (blend composition rounding order, purge tier math with all constants, nested-floor bundle plan, mode-selected amortization credit with min-cap, dual-basis pass-through, SPC evaluation, invoice waterfall, exposure aggregation)
- **Validations:** all 30 priorities expressed; explicit evaluation order stated for every multi-check endpoint (activation: line→die→screw→purge; blending: released→purity→compatibility→quantity; run start; SPC shape; confirm gate chain; create referential-before-index; overlap-before-buffer; OCC before state before domain; ERR_BAD_REQUEST catch-all last)
- **Endpoints:** all 50 in §4; side effects narrated in §3; OCC trio named with `expected_work_order_version` / `expected_die_version` / `expected_index_point_version` → `ERR_STALE_VERSION` (412)
- **Errors:** all 27 ids paired with trigger conditions in §2/§3 prose (verified)
- **Roles:** all 5 named with opaque-identity prose and capability summaries

**Hard Contract Reports:**
- Contract 1 (Field-Name Coverage): entities 97/97, request_body 70/70, query_params 13/13, path_params 12/12 — **PASS**
- Contract 2 (Rule Coverage): validations with priority ordering 30/30, OCC rejections 3/3, transitions 33/33, calculations 8/8, applies_to scopes and sibling branches symmetric — **PASS**
- Contract 3 (§3 Path Purity): 660 backtick tokens scanned, 0 path/method violations — **PASS**

**Zero-Silence Rule adjudications (precision pinned in prose):**
1. **Credit gate equality** — pinned "strictly greater than" for rejection; candidate exactly equal to `credit_limit_cents` passes.
2. **SPC control limits** — pinned strict inequality for `ooc` (exactly-on-limit is in control) and inclusive spec bounds for `spec_violations` (measurement exactly on a spec limit does not violate).
3. **Purge screw tiers** — boundary inclusivity pinned: at most 45 mm → 1.0; above 45 and at most 90 mm → 1.6; above 90 mm → 2.2. Color ladder ranks stated explicitly (NATURAL lightest … BLACK darkest).
4. **Schedule overlap** — half-open window semantics pinned; touching windows explicitly allowed.
5. **Die buffer** — gap definition spelled out for both orderings; zero-overlap adjacency with gap below `buffer_hours` still rejected.
6. **SPC quota** — floor of good metres divided by `sample_every_m`, pinned as "one posted sample per full `sample_every_m` metres".
7. **Amortization credit cap** — credit is the smaller of raw figure and `remaining_balance_cents`, never driving the balance below zero; adjustment bounds inclusive of 0 and `tooling_cost_cents`.
8. **DEPLETED flip** — at exactly zero `available_kg`; restored only when credit-back lifts it above zero.
9. **Rounding ladder** — per-quantity precision pinned in §2.6 (integer cents, 2-dp prices, 4-dp rates and SPC stats, 0.1-kg blend components, 2-dp percents and scrap), all round-half-up.
10. **Logical clock** — startup default pinned to exactly `2026-08-01T00:00:00Z`, never falls back to wall-clock.

The withheld difficulty/corner design files were not opened or referenced at any point.

## Step 5: Generate Unit Tests — 2026-08-15T02:05:23.000Z

Generation complete. All 85 tests collect cleanly under pytest.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/test_helpers/`**
- `types.py` — 14 entity TypedDicts + 16 status/domain enums; SPCSample/CutBundle/PurgeEvent correctly omit `updated_at`/`version` (common_fields: false per PRD §2.4)
- `constants.py` — purge bases/screw tiers/grade multipliers/COLOR_RANK, PASS_THROUGH_FACTOR 0.85, TOOLING_SURCHARGE_PCT 0.10, canonical fixture envelope (wall dim, 5000 m order, die economics), clock anchors
- `api_errors.py` — all 27 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (incl. `/_clock/set_current_utc`)
- `test_users.py` — `TEST_USERS` for the five opaque roles + `make_quality_inspector_headers(user_id)` for SoD flows
- `factories.py` — payload factories, input fields only
- `assertions.py` — per-entity assertions + `assert_amortization_invariant` / `assert_mass_balance` (PRD §2.9)
- `fixtures.py` — granular builders plus composite scenes: `plant_base`, `material_scene`, `running_scene`, `cascade_scene`, `closed_order_scene`, `two_mode_dies_scene`, `two_basis_orders_scene`
- `__init__.py` — barrel export

**`/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/test_suite/`**
- `conftest.py` — session-scoped `api` + per-role header fixtures
- `test_01_customers_credit.py` (8) · `test_02_pricing_pass_through.py` (9) · `test_03_dies_amortization.py` (10) · `test_04_materials_blending.py` (13) · `test_05_scheduling_assignments.py` (13) · `test_06_runs_spc.py` (15) · `test_07_completion_invoicing.py` (10) · `test_08_security_envelope.py` (7)

## Test counts per source
- **§1.8 queue A (Difficulty): 42 tests** — all 21 instances × ≥2 tests. Audit: all OK.
- **§1.9 queue B (Corner): 43 tests** — 44 non-stub instances covered minus 1 skip; the 3 `excluded_because:` stubs were not translated and their `difficulty_instance` pointers all resolve (`mass_balance_quarantine_rerelease`, `pass_through_monthly_avg_vs_shipment_date`, `purge_transition_tiers` — all asserted under queue A).

## Instances skipped (two-condition verdict)
- **Corner/entities/work_order_computed_input_ignored** — unique derivability FAILS. The instance asserts a work order creation carrying a client-supplied `pass_through_adj_cents_per_m: 999` succeeds and is ignored. PRD §3.4 defines the computed fields but never states that extra/client-supplied computed fields are accepted-and-ignored; a strict implementation rejecting unknown fields is fully PRD-consistent, so two PRD-only readers diverge. Coverage exists; derivability does not → gap left as a gap.

## Instance repaired (not skipped) — flagged for transparency
- **Difficulty/compensating_invariant/mass_balance_quarantine_rerelease**: its `setup_api_calls` specify a 200 kg regrind lot, but its pre-computed literals (regrind 100.0, virgin 861.5) only hold for a 100 kg lot — with 200 kg the PRD-pinned formula yields 192.3/769.2. I kept every asserted literal verbatim and set the regrind lot to 100 kg (the minimal setup repair making the instance's own numbers PRD-correct); the mass-conservation claim is unchanged.

## Tag-coverage audit
Automated sweep confirms: all 85 tests carry exactly one `Design:` tag on the final docstring line; every tag resolves to an existing instance in the correct queue/section; no tag points at a stub; every difficulty instance has ≥2 tests; every non-stub corner instance has ≥1. Separately verified: 120 long PRD quotations all survive a whitespace-normalized literal grep of `PRD.md` (C1), zero `pytest.mark.skip/skipif/xfail` markers, and zero "scaffold" mentions in generated code.

## Step 6: Generate Implementation — 2026-08-15T02:05:23.000Z

Implementation complete and verified. Summary:

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/workspace/implementation/`:
- `start.sh` — executable, guards `pip install` behind `python3 -c "import flask"`, `exec python3 app.py` in foreground on `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — entry point
- `state.py` — in-memory stores (empty at boot, zero seeding, no disk I/O), logical clock (default 2026-08-01T00:00:00Z), response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), auth (`X-User-ID`/`X-User-Role`, 5 roles), structural validators, pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/1/100/0), per-entity serializers
- `services.py` — all calculations and cascade logic
- `routes_part1.py` / `routes_part2.py` / `routes_part3.py` — endpoint handlers

## Coverage
- **Endpoints: 50/50** (incl. `POST /_clock/set_current_utc`)
- **State machines: 9** — Customer credit toggle; Die (DRAFT↔TRIAL→QUALIFIED rate-pinning, system QUALIFIED→IN_SERVICE on first activation, IN_SERVICE↔MAINTENANCE cycle, gated RETIRED); ExtrusionLine (IDLE/SETUP/RUNNING/DOWN); ResinLot (incl. system DEPLETED flips on exact-zero draw / credit-back); BlendBatch (BLENDED/QC_RELEASED/CONSUMED/QUARANTINED with `pre_quarantine_status` capture-restore and INV-MASS compensation); WorkOrder production status; WorkOrder `billing_status` dimension; LineAssignment; ProductionRun (RUNNING↔HOLD cyclic with MANUAL/SYSTEM origins)
- **Calculations: 8/8** — blend_composition (pinned rounding order, regrind availability absorption), purge_scrap_estimate (4 transition classes × 3 screw tiers × 2 grades), bundle_cut_plan (nested floor), tooling_amortization_credit (PER_METER/PER_KG variants, min-cap at remaining balance, INV-AMORT preserved), resin_price_pass_through (MONTHLY_AVG/SHIPMENT_DATE, factor 0.85, quote-month snapshot), spc_control_evaluation (strict OOC; on-limit in control), closeout_invoice_total (waterfall with 10% tooling surcharge), customer_open_exposure (per-order rounding, strict-> credit gate, equality allowed)
- **Validation priority chain** (auth→role→existence→OCC→SoD→state→cross-entity gates→domain rules→structural catch-all) with all 27 error IDs at their exact HTTP statuses

## Verification
Two smoke suites run against fresh `bash start.sh` boots: happy path (blend math 5.0/25.0/100.0/20.0 kg, 21 bundles with partial tail, amortization 12500→25500, invoice 112200 = 102000 + min-cap surcharge 10200) and cascade/error paths (SPC-OOC hold cascade, manual-hold SoD, consumed-batch quarantine, lot REVERSE with DEPLETED↔QC_PASSED flips, purge gate both directions, schedule/buffer conflicts, OCC 412 on all three guarded endpoints, credit gate boundary 30000==30000 allowed, MONTHLY_AVG vs SHIPMENT_DATE divergence, restate cascade exposure recompute 32040) — both **ALL PASS**; fresh boot confirmed empty store and default clock quote month.

## PRD interpretation decisions (multiple readings → choice)
1. **Missing OCC field** → deferred `ERR_BAD_REQUEST` at the structural tier (PRD calls it "non-optional" but the priority table places missing-field checks in tier 30); present-but-mismatched int → 412 at tier 4.
2. **Version bumps** — new entities start at `version: 1`; exactly one increment per affected entity per request (§2.9 "each affected entity ... version increments by one"), so a run completion that updates `produced_good_length_m` *and* closes the order bumps the WO once; exposure recomputes that change nothing do not bump the customer.
3. **Timestamps** — `created_at`/`updated_at`/request timestamp use wall-clock UTC (ms precision); the logical clock drives only month-based commercial logic (§2.5's enumerated uses). Clock echo and `planned_start`/`planned_end` normalize to `Z`, fractional digits only when nonzero.
4. **MONTHLY_AVG with clock before quote_month** (empty window) → fall back to the quote month alone (its point is guaranteed by creation), avoiding a spurious 422.
5. **Restate cascade never 422s** — `ERR_RESIN_INDEX_MISSING.applies_to` excludes restate, so orders whose basis window has an unpublished month are skipped rather than failing the restate.
6. **Invalid enum in `action`/`to`/`outcome`** → 400; valid enum but undefined transition from current state → 409 `ERR_INVALID_STATE`.
7. **Pagination out of range** (limit∉[1,100], offset<0, non-integer) → 400, per "accepts a minimum of 1, maximum of 100".
8. **Line unwinding literalism** — close returns the line to IDLE only from RUNNING; cancel only from SETUP (a never-run assignment closed leaves the line in SETUP, per the exact PRD wording).
9. **Run creation on a DOWN line** (reachable when a sibling run is HOLD) — no line transition is defined, so the line stays DOWN; only SETUP→RUNNING/stays-RUNNING per PRD.
10. **CONSUMED-batch quarantine while run already HOLD** — hold cascade fires only from RUNNING ("if RUNNING -> HOLD"), so run/line/assignments are untouched; `pre_quarantine_status`=CONSUMED still captured with no lot credit-back.
11. **RE_RELEASE SoD** compares against `last_qc_user_id` whenever set (a system-quarantined batch retains its prior inspector stamp); null passes.

## Step 7: Run Tests and Iterate — 2026-08-15T02:17:24.000Z

Clean 8-round sweep: all 8 rounds at 85/85. Task complete.

## Summary

- **Iterations run:** 2 (initial sweep: 81/85 in all 8 rounds, same 4 deterministic failures; post-fix sweep: 85/85 × 8 rounds, zero flakiness).

- **Tests deleted:** none. All 4 failing tests traced to verbatim PRD prose with unique derivability.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/test_suite/test_02_pricing_pass_through.py` — added `plant_base` to the `test_helpers` import list; `test_reprice_stale_work_order_version_rejected` used it without importing it (`NameError`). The test itself faithfully expresses PRD §2.7's reprice OCC rule.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/test_suite/test_07_completion_invoicing.py` — `test_consumed_batch_quarantine_cancels_assignments_without_credit_back`: corrected expected virgin `consumed_kg` from 861.5 to 961.5. The `cascade_scene` fixture blends without a `regrind_lot_id`, so per PRD §3.3's pinned composition (colorant = 1000/26 → 38.5; regrind = 0 when no lot supplied; virgin = exact remainder), the virgin draw is 961.5 kg, and the CONSUMED-quarantine "no lot credit-back" rule keeps it there. The 861.5 figure had been carried over from scenes that do supply a 100 kg regrind lot.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/workspace/implementation/state.py` — root cause of the two remaining failures: handlers serialize the response body *before* the request-end `flush_touches()` applies the PRD §2.4 version increment, so mutation responses carried the pre-mutation `version`. This broke `test_restate_stale_index_point_version_rejected` (PRD §3.4: "The point's `version` increments by one on restatement") and `test_failed_trial_reverts_to_draft` (PRD §3.2: "each [die transition] increments the die's `version` by one"). Unique derivability holds via PRD §2.7's OCC protocol: a second sequential restate/reprice can only succeed if the client observes the incremented version from the first write's response. Fix: `flush_touches()` now returns an id→entity map, and the `endpoint` wrapper runs a new `_refresh_serialized()` pass that copies post-flush `version`/`updated_at` onto any already-serialized copies of touched entities in the response payload (recursively, objects and list items). Error paths are untouched — a rejected request still skips the flush entirely, preserving "rejected writes must not mutate" semantics.

## Step 8: Finalize PRD — 2026-08-15T02:24:00.000Z

Done. Summary:

## PRD.md vs PRD_FINALIZED.md

- Line counts: 290 → 290 (0% line-count delta; 1 of 290 lines modified in place, ≈0.34% of lines touched). The change is one appended sentence inside an existing §2.2 bullet — no new sections.

## Changes (one edit total)

- **§2.2 (Standard Success Response Format)** — **revise** — appended one sentence to the `data`-field bullet pinning that the resource object returned by a create/modify operation presents the resource *after* the request's mutations are fully applied: `version` already includes that request's increment (§2.4) and `updated_at` is the refreshed timestamp, so an OCC-guarded follow-up write (§2.7) can take its expected version straight from the write's response — `implementation/state.py:161-174` (`flush_touches` now returns the id→entity map), `state.py:177-191` (`_refresh_serialized`), `state.py:288-294` (`endpoint` wrapper applies the refresh post-flush, pre-envelope).

## Items traced to `<step_7_diff>` with no PRD edit (already uniquely determined)

- `test_suite/test_02_pricing_pass_through.py` import fix — pure test harness bug (`NameError` for `plant_base`); PRD §2.7's reprice OCC rule needed no change.
- `test_suite/test_07_completion_invoicing.py` 861.5 → 961.5 — pure test-expectation bug. PRD §3.3 already pins the composition verbatim (colorant = `target/(1+let_down_ratio)` half-up to 1 dp → 38.5; base total = exact remainder; no regrind lot → availability zero → `regrind_kg` 0; `virgin_kg` = exact remainder 961.5) and the CONSUMED-quarantine no-credit-back rule. Impl matches PRD exactly (`services.py:232-248` `blend_composition`; `routes_part2.py:151-166` CONSUMED branch performs no `credit_back_lots`).

## Per-edit pre-edit search log (NO-NEW-MISMATCH)

**Edit 1 (§2.2 sentence):**
- (a) Subject: contents of successful write responses — whether the returned resource object carries post-mutation `version`/`updated_at`.
- (b) Impl paths enumerated and read in full: `state.py` `endpoint` wrapper (278-304, refresh applied to every successful response; `ApiError` path skips flush entirely), `flush_touches` (161-174, one bump per touched entity), `_refresh_serialized` (177-191, recursive, only overwrites `version`/`updated_at` keys that exist, matches by `id`); every mutating handler returning the mutated primary resource — `routes_part1.py` credit-status (40-58), die transition (207-239), amortization adjustment (242-278), lot QC incl. REVERSE cascade (343-374); `routes_part2.py` batch QC (122-180), confirm (270-294), reprice (297-322), cancel (325-353), invoice (356-375); `routes_part3.py` activate (122-187), close (190-209), assignment cancel (212-233), run hold-status (318-359), complete (362-418), restate (574-597); every creation handler returning a version-1 as-created object (created entities are never `mark`-ed, so version 1 *is* their post-request state); lean-trio responses (`create_sample` 422-471, `create_purge` 496-528, bundles) whose serializers carry no `version`/`updated_at`; `set_clock` (600-612) returning non-resource `{current_utc}`; cascaded secondary entities (`draw_lots`/`credit_back_lots` 203-226, `recompute_exposure` 38-46, `restate_cascade` 89-120, hold cascades 164-189) which never appear embedded in any response payload (serializers are flat; no mutating endpoint returns a list).
- (c) Wording adjustments from the search: scoped the sentence to "the created or updated resource object" rather than any claim about every cascade-mutated entity; added "for resources that carry them" so the lean trio (§2.4) isn't mis-described; relied on the existing "Unless otherwise noted" qualifier to keep the clock endpoint (§2.5's own response shape) out of scope.

## Step 9: Complete PRD — 2026-08-15T02:41:03.000Z

All 14 intended hunks, all single-paragraph in-place edits. Task complete.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1919_plastics_extrusion_profile_plant/workspace/PRD_COMPLETED.md`

**Line counts:** PRD_FINALIZED.md 290 lines → PRD_COMPLETED.md 290 lines (all changes are in-paragraph; no sections or paragraphs added). **Char delta:** 58,003 → 60,609 (+2,606 chars). Diff touches exactly 14 paragraphs (14 lines replaced).

**Counts:** 13 ambiguity-pins, 1 mismatch-revision.

**Changes (one per bullet):**

- §2.3 — insert — ambiguity — list-sort ties on equal `created_at` broken toward the earlier-created resource — `implementation/state.py:496-497` (sort key `(created_at, _seq)`)
- §2.4 — insert — ambiguity — `version` starts at 1 when a resource is created — `implementation/state.py:203` (`stamp_new` sets `version = 1`)
- §2.5 — insert — ambiguity — logical clock accepts any supplied instant, earlier or later; no monotonicity check — `implementation/routes_part3.py:601-612` (`CLOCK["now"] = dt` unconditionally)
- §2.7 — insert — ambiguity — a missing or non-integer expected-version field is `ERR_BAD_REQUEST` evaluated in the structural tier; only a well-formed stale value is `ERR_STALE_VERSION` — `implementation/routes_part2.py:301-314`, `implementation/routes_part1.py:252-273`, `implementation/routes_part3.py:583-593`
- §2.8 — revise — mismatch — workflow selector fields (`action` on credit-status/batch-QC/hold-status, `outcome` on lot QC, `to` on die transition) are validated immediately after existence, so an unrecognized selector surfaces `ERR_BAD_REQUEST` *before* the SoD and from-state tiers, qualifying the prior blanket "ERR_BAD_REQUEST runs last of all" — `implementation/routes_part1.py:44-46, 211-213, 347-350`, `implementation/routes_part2.py:126-129`, `implementation/routes_part3.py:322-324`
- §3.3 — insert — ambiguity — the lot-`REVERSE` quarantine cascade does not stamp `last_qc_user_id`; a quarantined batch keeps its prior value (possibly none), and a later `RE_RELEASE` SoD check is measured against that earlier stamper — `implementation/routes_part1.py:364-373` (no stamp in cascade) vs `implementation/routes_part2.py:131-134`
- §3.3 — insert — ambiguity — quarantining a `CONSUMED` batch whose consuming run is already `HOLD` still quarantines the batch (no credit-back, `pre_quarantine_status` = `CONSUMED`) but the hold cascade does not re-fire; run and line are untouched — `implementation/routes_part2.py:151-166` (`hold_run_system` called only when run is `RUNNING`)
- §3.4 — insert — ambiguity — restatement cascade: if recomputing an affected order hits a window month with no published point, the restate does not fail; the order is left untouched — `implementation/services.py:105-112`
- §3.4 — insert — ambiguity — when the clock month precedes `quote_month` (backwards clock move): direct pass-through evaluation falls back to the quote month alone; the restate cascade treats the window as empty and skips the order — `implementation/services.py:59-62, 98-100`
- §3.4 — insert — ambiguity — an `open_exposure_cents` recomputation that leaves the value unchanged is no mutation: customer `version`/`updated_at` do not move — `implementation/services.py:38-46`
- §3.4 — insert — ambiguity — reprice is defined only from `QUOTED` and `CONFIRMED`; from `SCHEDULED`/`IN_PRODUCTION`/`CLOSED`/`CANCELLED` it is `ERR_INVALID_STATE` — `implementation/routes_part2.py:309-311`
- §3.5 — insert — ambiguity — a window whose `planned_end` is not strictly after `planned_start` is malformed (`ERR_BAD_REQUEST`) — `implementation/routes_part3.py:52-58`
- §3.5 — insert — ambiguity — purge-gate reference tie-break extended: beyond equal `planned_end` and equal `created_at`, the later-created assignment wins — `implementation/routes_part3.py:154-159` (`_seq` final tie-break)
- §3.6 — insert — ambiguity — run start never consults line status: a line left `DOWN` by a held sibling run stays `DOWN`, and an `ACTIVE` assignment may host more than one live run — `implementation/routes_part3.py:290-293`

**Consciously left unpinned (impl defect, not a spec interpretation):** an unparseable (but string-typed) `planned_start`/`planned_end` is not rejected at creation; the assignment is stored with `None` dates and serialization then crashes into the 500 handler (`implementation/routes_part3.py:52-54`, `implementation/state.py:98-102`). Pinning either "400 at creation" (contradicts impl) or "500 + poisoned resource" (a crash path) would be worse than silence, so it was left as-is.
