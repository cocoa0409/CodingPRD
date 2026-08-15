# Worklog — task_1775_site_utility_excavation_contracting

## Step 1: Create Task Directory — 2026-08-14T15:12:00.000Z

Task directory `tasks/task_1775_site_utility_excavation_contracting/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker. Treated as DONE per instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T16:17:00.000Z

Scaffold generation complete. All three files written, lint clean, and self-audits pass.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1775_site_utility_excavation_contracting/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1775_site_utility_excavation_contracting/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1775_site_utility_excavation_contracting/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

## Counts

- **SCAFFOLD**: 15 entities, 13 state machines, 10 calculations, 11 ordered validation priorities, 74 endpoints, 34 error codes, 6 roles, 2 OCC concurrency rules
- **Difficulty design**: 9 rules × 2 instances = **18 instances** (all §0.5 differentiation clauses honored)
- **Corner design**: **62 instances (60 active + 2 excluded_because stubs)** across all 9 taxonomy sections; 735 total calls linted
- **Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Notable design decisions

- **Archetypes**: workflow_orchestration + compliance_audit; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. Flat topology (all FK references, prioritized per skill), cyclic state shape, segregation-of-duties role model, immediate consistency.
- **Difficulty maxima exercised**: parallel state dimensions on Project (status × work_posture); revision cycles on TrenchSafetyPlan/ChangeOrder/AsBuiltPackage; INSTALLED→INSTALLING rework loop on PipeSegment; a depth-3 cascade (turbidity reading → permit SUSPENDED → dewatering segments ON_HOLD → their PROPOSED windows CANCELLED) and a depth-2 stop-work cascade; GROUNDWATER condition → conditional plan-void cascade with pinned evaluation order (constraint-propagation mode c).
- **Rule 8 contrast**: owner-level half-open `[start, end)` overlap (touching allowed) vs project-level 120-minute buffer-expanded clearance (exactly 120 passes) — different resources, different interval geometry.
- **Dual-variant calcs in different domains**: ChangeOrder PROVISIONAL vs FINAL pricing (287500 vs 327750 cents, reconciled delta) and PipeSegment MEAN vs WORST_LIFT compaction summaries (95.4 vs 95.0 on identical input).
- **Pinned rounding order** (mode b): per-cost-line then per-tier-slice `round_half_up` — yields 54822 where the alternative order yields 54821; all formula-derived asserts were executed in Python and written as literals.
- **OCC**: two §1.2.1 rules on Project.version (window booking, CO create-with-supersede); every `expected_project_version` in test recipes references a `${var}` capture (lint rule (e) clean).
- **Roles**: UtilityOwnerRep is `entity_backed:UtilityOwner` (ownership checks on window/as-built/CO reviews); SoD enforced by user-id comparison (SafetyOfficer/Inspector reviewers ≠ submitters/recorders); CO review is amount-gated at 2500000 cents (owner rep above, PM below).
- **Clock**: `POST /site-utility/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z` and pinned 4-phase evaluation order (ticket activate → ticket expire → permit activate/expire → window activate/miss), driving all time-based transitions deterministically.
- Fixes made during QA replay: removed unproducible `REVOKED` permit state, made permits ACTIVE-at-create inside their effective window, lowered `MIN_COVER_FT` to 0.5 (so the 2-lift shallow-segment chains can pass the inspection gate), fixed daily-volume instance flows so the volume branch (not flow) classifies, and added the missing `pipe_segment_id?` reverse-filter on `GET /unforeseen-conditions`.

No sibling task directories were inspected; the scaffold derives solely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-08-14T16:17:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1775_site_utility_excavation_contracting/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T16:45:00.000Z

The PRD is complete and all verifications pass. Final summary:

## Task Complete

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1775_site_utility_excavation_contracting/workspace/PRD.md` — 333 lines, ~8,515 words.

**Structure:** §1 Introduction (2 paragraphs, business-context angle) → §2 Global Specifications (11 subsections: 2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, plus 8 domain-derived subsections — audit trail/identity, logical clock, work-posture hold cascades, monetary/fiscal caps, measurement precision, OCC, validation priority order, cross-project referential integrity) → §3 Business Logic (9 subsections organized by business-process timeline: registry/setup → locates & potholes → trench safety → pipe installation → shutdown windows → discharge permits → unforeseen conditions → change orders → as-builts & closeout) → §4 endpoint table (74 rows, 4 columns) → §5 error catalogue (34 rows, 2 columns).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 110 required, 110 present, 0 missing
- endpoints[].request_body: 76 required, 76 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in prose (§2.10 ordered narrative, incl. pinned sub-orders for priority 7 safety gates and priority 8 temporal rules), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write operation + expected_project_version + ERR_STALE_VERSION/412 all named in §2.9; stale-supersede rationale included), 0 missing
- state_machines[].transitions: 64 checked, 64 fully expressed (34 via explicit `FROM → TO` pair tokens, 30 via equivalent from/to prose — each manually verified), 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise reconstructible prose (both PROVISIONAL/FINAL pricing variants with pinned per-line-then-per-slice rounding; MEAN/WORST_LIFT summary variants; discharge classification precedence with inclusive/exclusive boundaries), 0 missing
- validations[] conditions: 34 error IDs, 34 matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 74 endpoints checked, all side effects (cascades, ledger movements, version bumps, supersede) narrated, 0 missing
- entities[].fields[] structured content: all defaults, nullability, and computed-field semantics reconstructible from prose, 0 missing
- sibling-branch symmetry: review decision pairs, renew-from-ACTIVE vs EXPIRED, PROPOSED vs CONFIRMED cancel rules, tier slices all rendered at equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 639
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notable decisions:**
- §2.2 was appended byte-identically from `section-2.2-response-structure.md` (verified `src in prd`); an initial audit false-negative from the fenced JSON blocks flipping naive backtick parity was diagnosed and the checker corrected to strip fences first.
- Unit-conversion embedding per the scattering guideline: 672 hours rendered as "672 hours — twenty-eight days"; 2,500,000 cents as "2,500,000 cents — twenty-five thousand dollars"; 10,000,000 cents as one hundred thousand dollars.
- `UtilityOwnerRep` entity-backed identity translated explicitly in §2.1 (ownership checks compare `utility_owner_id` to `X-User-ID`); the five other roles documented as opaque identifiers that are recorded but never compared to entity ids.
- All pinned evaluation orders preserved: clock-transition order (tickets activate → tickets expire → permits → windows), readiness-recompute order (conditions → plans → segments), classification precedence (turbidity → daily volume → flow), and validation priorities 1–11.
- Boundary inclusivity stated explicitly everywhere the scaffold pins it (slope ratio 1.5-on-`SOIL_C` passes, 0.2% slope deviation passes, exactly-120-minute buffer passes, price exactly at cap allowed, turbidity boundary inclusive vs flow/volume strictly-greater).
- The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T17:30:00.000Z

Generation complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1775_site_utility_excavation_contracting/`)

**test_helpers/** (9 modules): `types.py` (16 entity TypedDicts + 18 enums; `AuditEvent` correctly carries only `id`+`created_at` per its append-only contract), `api_client.py` (`ApiClient(GenericApiClient)` with one method per PRD §4 endpoint, all under `/site-utility`), `api_errors.py` (34 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`), `assertions.py` (permissive per-entity asserts — identity/timestamps/version/enum domains only), `constants.py` (PRD thresholds: 672h ticket validity, 6/12in pothole tolerances, slope ratios, compaction required pcts, pricing tiers, 120-min buffer), `test_users.py` (shared headers for the 5 opaque roles + `make_utility_owner_rep_headers(owner_id)` for the entity-backed role), `factories.py` (input-only payload factories; `None` overrides omit optional keys), `fixtures.py` (composite chains: active-ticket context, READY→INSTALLING→INSTALLED→BACKFILLING→COMPLETE drivers, closeout-ready project, OCC-version-refreshing window/CO creators), `__init__.py` barrel.

**test_suite/** (12 files): `conftest.py` + `test_01…test_11`, 95 tests total.

## Test counts per queue
- **Queue A (Difficulty): 36 tests** — all 18 instances × exactly 2 tests each (second tests cover a distinct PRD-derived facet: complementary boundary class, governing-set exclusion, tier-crossing markup, unblock-after-resolve, terminal-state complement, etc.).
- **Queue B (Corner): 59 tests** — all 60 non-stub instances minus 1 skipped.

## Skipped instances
- `Corner/entities/compaction_pct_input_ignored` — **SKIP (computed-field / two-reader failure)**: the test injects a client-supplied `compaction_pct: 999` and asserts the server ignores it. The PRD lists the create inputs and the computation rule but never states that unknown/computed input fields are ignored rather than rejected with `ERR_VALIDATION`; a faithful PRD-only implementer could do either. No test emitted (no placeholder, no skip marker).
- Both `excluded_because:` stubs (`change_order_correct_result_covered`, `pothole_tolerance_and_compaction_constants_covered`) were not translated; their difficulty-instance pointers were verified to resolve (`co_price_pinned_rounding_order`, `compaction_exactly_at_required_passes`).

## Audit results
- Tag coverage script: all 18 difficulty tags ≥2 tests, 59/60 corner tags ≥1 (only the intentional skip short), zero orphan tags, zero dual/untagged tests; every `Design:` line is the docstring's last line and resolves to a real instance.
- PRD-citation pass: every quoted span in all 95 docstrings survives whitespace-normalized literal grep of `workspace/PRD.md` (≥8-word window check). Priority-ordering tests (pothole state-beats-safety, CO referential-beats-fiscal, window-in-past-beats-notice, owner-overlap-beats-buffer) carry the §2.10 sub-order citation.
- `pytest --collect-only`: 95 tests collected, 0 import errors. No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments/docstrings.
- One deliberate disambiguation: `proposed_window_misses_at_start` advances the clock 1 second past `window_start` (10:00:01Z) because PRD's "when its start passes" is ambiguous at exact equality — both reader variants agree 1s later.

## Step 6: Generate Implementation — 2026-08-14T17:30:00.000Z

## Summary

### Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_1775_site_utility_excavation_contracting/workspace/implementation/`:

- **`start.sh`** — executable launcher; guards `pip install` behind a `python3 -c "import flask"` probe (per-test reboot safety), then `exec python3 app.py` in the foreground.
- **`requirements.txt`** — `flask>=3.0,<4.0`.
- **`app.py`** — Flask entry point, error handlers, and all 55 endpoint handlers across 13 resource groups (75 URL rules once Flask's auto-registered HEAD/OPTIONS variants are counted).
- **`core.py`** — auth/role middleware, entity stamping (`id`/`created_at`/`updated_at`/`version`), audit-event appender, work-posture recompute, stop-work cascade, groundwater readiness recompute, permit suspend/reinstate cascades, segment compaction summary recompute, and the pinned 4-phase clock-advance evaluator.
- **`helpers.py`** — response envelope (`meta.api_request_id`/`api_request_timestamp` + `response_type` + `data`, with pagination fields `limit`/`offset`/`total_count`/`has_more`), error envelope (`data.error_id`/`data.message`), logical `Clock` (pinned at `2026-08-01T00:00:00Z` at boot, never falls back to wall clock), ISO 8601 parsing/formatting with 3 fractional digits, `round_half_up` on `Decimal`, request body validators.
- **`store.py`** — empty in-memory dicts per entity; no seeding anywhere (verified — no `seed_*` and no module-load population).

### Coverage

- **Endpoints**: all 55 routes from the scaffold's §1.5 table are wired (projects, utility-owners, locate-tickets, pothole-verifications, trench-safety-plans, pipe-segments, installation-inspections, shutdown-windows, discharge-permits + readings, compaction-tests, as-built-packages, unforeseen-conditions, change-orders, and `_clock/set_current_utc`).
- **State machines**: all 12 implemented with their preconditions and side effects — Project (ACTIVE→CLOSING→CLOSED with the closeout completeness bundle), work_posture (CLEAR↔STOPPED with segment cascade), LocateTicket (incl. skipped-window → EXPIRED, renew from ACTIVE/EXPIRED), PotholeVerification (incl. CONFLICT-only supersede), TrenchSafetyPlan (incl. REJECTED→DRAFT revision bump, GROUNDWATER voiding), PipeSegment (full pipeline + rework loop + ON_HOLD with hold_reason/resume_status), InstallationInspection (RECORDED→CONFIRMED/DISPUTED), ShutdownWindow (PROPOSED/CONFIRMED/ACTIVE/COMPLETED/MISSED/REJECTED/CANCELLED with ledger release), DischargePermit (ISSUED/ACTIVE/SUSPENDED/EXPIRED), CompactionTest, AsBuiltPackage, UnforeseenCondition (OPEN↔MITIGATING/RESOLVED/CLOSED_NO_ACTION), ChangeOrder (incl. create-supersedes-open and REJECTED→DRAFT revise).
- **Calculations**: all 8 implemented with the pinned rounding order — `change_order_price` (round each cost line, sum, then round each marginal tier slice; tiers at 2.5M/10M cents with 15%/10%/5%), `as_built_acceptance` (1.0 ft / 1% length tol at 0.1 ft, 0.1 ft / 0.5% invert tol at 0.01 ft, both inclusive), `compaction_test_result` (round-half-up to 0.1 pct, ≥ required), `segment_compaction_summary` (mean + worst-lift variants, per-lift PASS coverage for `lifts_satisfied`), `lifts_required` (ceil of `(invert + diameter/12 + bedding)`), `trench_slope_requirement` (0.75/1.0/1.5 by soil class, 20 ft engineered-design rule), `installation_inspection_result` (bedding ∧ joints ∧ |slope Δ| ≤ 0.2 ∧ cover ≥ 0.5), `discharge_classification` (precedence EXCEEDS_TURBIDITY → EXCEEDS_VOLUME → EXCEEDS_FLOW → NORMAL; turbidity ≥, volume >, flow >; daily volume summed over same UTC date), `window_hours_ledger` (sum of durations in PROPOSED/CONFIRMED/ACTIVE), `readiness_recompute` (pinned 3-step: collect OPEN GROUNDWATER → void APPROVED SLOPING/BENCHING → revert READY segments).
- **Validations**: priority order honored — auth (401) → role/SoD (403) → body shape (400) → FK existence (404) → OCC `expected_project_version` (412) → state (409) → safety gates (posture → locate → slope/depth → permit; 409/422) → temporal (window-in-past → notice → owner-overlap → project-buffer → reading-window) → cross-entity integrity (422 cross-project, then plan/potholes/inspection/segment/condition/CO gates) → aggregate/uniqueness (409) → fiscal caps (422/409).

### Notable implementation decisions

1. **Validation sub-ordering**: within the safety-gate priority the order is posture → locate → slope/depth → permit (per PRD §2.10), which means `ERR_PROJECT_STOPPED` fires before `ERR_LOCATE_NOT_ACTIVE` and both fire before the priority-9 cross-entity checks (`ERR_PLAN_NOT_APPROVED`, `ERR_POTHOLES_OUTSTANDING`, `ERR_INSPECTION_NOT_PASSED`).
2. **OCC before state and temporal**: `ERR_STALE_VERSION` (priority 5) is checked before window temporal rules, so a stale request surfaces 412 rather than a temporal error.
3. **Owner registration produces no audit event**: `AuditEvent.project_id` is non-nullable in the scaffold and utility owners are not project-scoped, so the endpoint skips auditing (the audit trail is per-project; a project-less event would violate the entity model).
4. **Window create touches Project**: booking a window increments `Project.version` (per §2.9) — implemented via `touch(project)` after window creation, in addition to `committed_shutdown_minutes` accruing on the owner.
5. **Half-open intervals**: window overlap uses `[start, end)` semantics so touching endpoints do not overlap; the 120-minute project buffer accepts exactly 120 minutes of clearance.
6. **Clock evaluation order is pinned** as the PRD requires: (1) SUBMITTED→ACTIVE tickets, (2) ticket expiry (so a skipped window lands EXPIRED), (3) permit ISSUED→ACTIVE / →EXPIRED, (4) window PROPOSED→MISSED / CONFIRMED→ACTIVE (gated on CLEAR posture) / →MISSED.
7. **Renewal edge case**: renewing an EXPIRED ticket only reactivates it if the new `valid_until` is strictly in the future; otherwise it stays EXPIRED but `renew_count` still increments (per the PRD's "renewal too late to matter" rule).
8. **Permit creation status**: computed once at create — `ACTIVE` iff `effective_from <= now < effective_to`, else `ISSUED`; clock handles later transitions.

### Smoke verification

Server boots cleanly from a fresh process and exercised paths include: project create (envelope shape correct, system fields stamped), owner registry, locate ticket DRAFT→SUBMITTED→ACTIVE via clock advance, pipe segment create (lifts_required correctly computed as 7 for 5 ft invert + 12 in diameter + CLASS_B bedding), trench plan Foreman→SafetyOfficer approval, mark-ready, change-order creation with pricing math verified end-to-end (estimates: 100 h×5000 c labor + 50 h×8000 c equipment + 100000 c material = 1,000,000 direct + 150,000 markup = 1,150,000 provisional; actuals 110 h labor → final 1,207,500, delta +57,500, project ledger 1,207,500), SoD rejection on self-review, stop-work cascade (posture STOPPED, INSTALLING segment → ON_HOLD with hold_reason STOP_WORK and resume_status INSTALLING, then resume on resolve), and stale-version rejection on the OCC-guarded window create.

## Step 7: Run Tests and Iterate — 2026-08-14T18:05:00.000Z

Summary — task_1775_site_utility_excavation_contracting diagnostic loop complete.

**Iterations run:** 3 sweeps of 8 parallel rounds each (95 tests/round).
- Sweep 1 (baseline): rounds passed 95/95, 93, 94, 94, 94, 94, 93, 95 — flaky union: `test_audit_trail_entity_type_filter` (5/8 rounds), `test_inspection_fail_rework_loop` (3/8 rounds).
- Sweep 2 (after ordering fixes): 7×95/95; one round failed `test_daily_volume_crossing_flips_classification` with a transport-level `ConnectionError: RemoteDisconnected`.
- Sweep 3 (after client transport fix): **all 8 rounds 95/95 — clean exit.**

**Tests deleted:** none. Both failing tests passed STEP 1 (PRD §3.1/§2.4 cover chronological audit retrieval verbatim; PRD §3.4 covers "most recently created CONFIRMED inspection" verbatim) and STEP 2 (fixtures/roles/payloads faithful to PRD).

**Fixes applied to `implementation/`** (`workspace/implementation/app.py` — all the same root cause: random-uuid tie-breaks on a fixed logical clock destroyed chronological determinism):
- `list_response()` (line ~59): default list sort changed from `(created_at, id)` to stable sort by `created_at` only — PRD §2.3 default ordering, ties keep insertion order.
- `list_audit_events()` (line ~171): same change — PRD §2.4 "appends one audit event per mutated resource … retrievable in chronological order"; uuid tie-break could order the submit event before the create event.
- `_latest_confirmed_inspection()` (line ~594): stable sort by `created_at`, take last — PRD §3.4 "most recently created CONFIRMED inspection"; uuid tie-break could pick the older FAIL over the newer PASS, causing the flaky 409 `ERR_INSPECTION_NOT_PASSED`.
- `list_permit_readings()` (line ~1192): sort by `(recorded_at, created_at)` without the `id` tie-break — PRD §3.6 "by `recorded_at`, then `created_at`".

**Fixes applied to `test_helpers/`**:
- `test_helpers/api_client.py` (module init): set `api_client.session.headers["Connection"] = "close"`. The runner's per-test-server isolation SIGKILLs and respawns the server before every test, while the session-scoped `requests.Session` pooled keep-alive connections to the dead process — a ~0.1% stale-connection race surfacing as `RemoteDisconnected` on a random test. Forcing connection close makes every request open a fresh connection, eliminating the race. Transport-only change; no assertion touched.

No PRD-required implementation checks were weakened; no assertions downgraded; no tests skipped.

## Step 8: Finalize PRD — 2026-08-14T18:15:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1775_site_utility_excavation_contracting/workspace/PRD_FINALIZED.md`.

## Size

- **PRD.md:** 332 lines / 61,514 chars — **PRD_FINALIZED.md:** 332 lines / 62,023 chars — **delta +0.827%** (all edits inline; no lines or sections added).

## Changes (one bullet per edit)

- **§2.3** — revise — default list ordering now pins that resources sharing the same `created_at` keep creation order — `implementation/app.py:51-67` (`list_response`).
- **§3.1** — revise — audit-trail retrieval now pins that events sharing the same `created_at` appear in append order — `implementation/app.py:163-176` (`list_audit_events`), `implementation/core.py:90-105` (`audit`).
- **§3.4** — insert — new sentence defining "most recently created `CONFIRMED` inspection" among equal `created_at` as the one recorded last — `implementation/app.py:587-597` (`_latest_confirmed_inspection`), call sites `app.py:606` (reopen) and `app.py:625` (start-backfill).
- **§3.6** — revise — readings listing now pins that readings equal on both `recorded_at` and `created_at` keep recording order — `implementation/app.py:1184-1197` (`list_permit_readings`).

The `test_helpers/api_client.py` `Connection: close` fix is transport-only (client session reuse vs. per-test server restarts) with no API behavioral surface — no PRD edit.

## Per-edit pre-edit search log

**Edit 1 (§2.3)** — (a) Subject: default list ordering. (b) Enumerated: `list_response` def (`app.py:51-67`) plus all 13 call sites — `app.py:102, 205, 257, 373, 505, 700, 836, 998, 1142, 1343, 1423, 1566, 1713` (projects, owners, tickets, potholes, plans, segments, inspections, windows, permits, compaction tests, conditions, as-builts, change orders); grep confirmed no call site passes `sort_key`, so all use the stable `created_at`-only sort; the two non-default listings fall under the pre-existing "unless a specific list documents a different ordering" carve-out; `stamp_new` (`core.py:45-52`) confirmed `created_at` comes from the logical clock, making ties common. (c) Added the "common under the logical clock" rationale and phrased the tie-break as "keep the order in which they were created" to match stable-sort-over-insertion-order without prescribing an algorithm.

**Edit 2 (§3.1)** — (a) Subject: audit-trail ordering. (b) Enumerated: `audit()` (`core.py:90-105`, the only append path, invoked by every mutation including cascades and clock advance in `core.py:140-401`) and `list_audit_events` (`app.py:163-176`, the only retrieval path); §2.4 defers to §3.1 ("as described in §3.1"), so the §3.1 edit covers §2.4 verbatim. (c) Chose "order they were appended" (not "created") to match both the create→submit sequence and multi-event clock advances.

**Edit 3 (§3.4)** — (a) Subject: "most recently created CONFIRMED inspection" selection. (b) Enumerated: `_latest_confirmed_inspection` (`app.py:587-597`) and both call sites (`app.py:606`, `app.py:625`); PRD grep confirmed "most recently" appears only in §3.4, and the reopen-install sentence ("the latest confirmed inspection is a FAIL") shares the same helper. (c) Inserted a standalone definitional sentence before the reopen sentence so both gates inherit it; used "recorded last" (domain language: "an Inspector records an inspection") instead of implementation jargon.

**Edit 4 (§3.6)** — (a) Subject: readings list ordering. (b) Enumerated: `list_permit_readings` (`app.py:1184-1197`, the only readings listing); cross-checked the daily-volume classification loop (`app.py:1226-1239`) — it iterates unsorted but computes an order-independent sum, so the existing "processed chronologically" sentence stays accurate and was left verbatim; the §4 endpoint-table row was left as summary. (c) Inserted the tie-break inside the existing em-dash pair, preserving "rather than the default ordering" and the filter clause.

## Step 9: Complete PRD — 2026-08-14T18:35:00.000Z

All edits applied cleanly. Final verification of the diff confirms exactly the intended changes and nothing else.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1775_site_utility_excavation_contracting/workspace/PRD_COMPLETED.md`

**Source:** `PRD_FINALIZED.md` (existed; copied then edited in place). 332 lines / 62,341 chars → 333 lines / 67,730 chars (**+1 line, +5,389 chars**; 29 prose lines touched, no sections added).

**Counts:** 23 ambiguity-pins, 9 mismatch-revisions.

### Changes

- **§2.2** — insert — ambiguity — unknown path or unsupported method → `ERR_NOT_FOUND` (404) — `implementation/app.py:31-38`
- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit`, negative `offset` → `ERR_VALIDATION`; `has_more` is true exactly when `offset`+`limit` < `total_count` — `implementation/helpers.py:232-252,45-51`
- **§2.4** — revise — mismatch — replaced "one audit event per mutated resource" with impl's actual coverage: one event per action-target + named cascade events (groundwater voids/reverts, dewatering window cancels, reinstate resumes, supersedes, clock transitions); secondary bookkeeping (posture flips, holds/resumes, permit suspension, exceedance counts, ledger movements, version bumps, `tie_in_completed`, compaction recomputes, `OPEN→MITIGATING`) and all utility-owner mutations append no audit events — `implementation/core.py:90-105,140-265`, `implementation/app.py:182-199`
- **§2.6** — revise — mismatch — posture flips `STOPPED` at stop-work report and recomputes only at stop-work resolution; `OPEN→MITIGATING` at approval does not recompute (project stays `STOPPED` with sole MITIGATING stop-work condition); "leaves OPEN" → "is resolved" — `implementation/app.py:1795-1797,1611-1614`, `implementation/core.py:111-153`
- **§2.9** — insert — ambiguity — OCC check is strict equality; a newer token fails like an older one — `implementation/app.py:927,1660`
- **§2.10** — revise — mismatch (x3 in one pass) — SOD moved from step 2 to immediately after the from-state gate; pothole-perform exception (locate check before posture check); appended local-reorder sentence (shutdown create: cross-project checks right after existence, before duration/OCC/temporal; condition create: project-`ACTIVE` gate before resolving optional `pipe_segment_id`; change-order review: body validation and CO lookup before authentication) — `implementation/app.py:749-750,858-859,1360-1361,399-404,904-938,1534-1541,1755-1758`
- **§3.1** — insert — ambiguity (x2) — `min_notice_hours` non-negative int, `max_shutdown_hours` positive int; project `contingency_cents`/`single_co_cap_cents` non-negative ints (zero allowed) — `implementation/app.py:188-189,80-81`
- **§3.2** — insert — ambiguity (x4) — renewal valid only from `ACTIVE`/`EXPIRED`; `design_depth_in` positive int, `design_offset_in` non-negative int; perform measurements non-negative ints; locate-ticket list filters `project_id`/`status` — `implementation/app.py:291-292,324-325,393-394,254-263`
- **§3.3** — insert — ambiguity (x2) — `max_depth_ft` positive; `slope_ratio` omissible at draft even for SLOPING/BENCHING; revise may null `slope_ratio` and leaves `submitted_by_user_id`/`reviewed_by_user_id` untouched — `implementation/app.py:665-669,723-728,779-790`
- **§3.4** — insert — ambiguity (x4) — segment create field constraints + `requires_dewatering` defaults false; slope deviation compared unrounded, inspection slope/cover non-negative; compaction test field constraints; `lift_number` filter must parse as integer — `implementation/app.py:461-466,803-814,1286-1289,1337-1342`
- **§3.4** — revise — mismatch — statistics stay null until first accepted **PASS** (accepting only FAIL tests triggers no recompute; earlier accepted FAILs join the governing set at the first PASS-triggered recompute) — `implementation/app.py:1366-1367`, `implementation/core.py:268-290`
- **§3.5** — insert — ambiguity (x2) — `duration_minutes` fractional minute rounds down; window review has no SOD check (no proposer identity captured) — `implementation/app.py:919-920,977-985,1024-1053`
- **§3.6** — insert — ambiguity (x2) — permit compliance limits positive ints; reading `flow_gpm`/`turbidity_ntu` non-negative ints, `duration_min` positive int — `implementation/app.py:1103-1105,1206-1208`
- **§3.7** — revise — mismatch — posture recomputes when a stop-work condition is *resolved* (from OPEN or MITIGATING), not "leaves OPEN" — `implementation/app.py:1611-1614`
- **§3.8** — insert — ambiguity (x2) — five pricing inputs non-negative (hours numeric, rates/material integer cents); revise retains `submitted_by_user_id`/`reviewed_by_user_id` — `implementation/app.py:1643-1647,1809-1843`
- **§3.8** — revise — mismatch — approval's `OPEN→MITIGATING` move does not recompute work posture — `implementation/app.py:1795-1797`
- **§3.9** — insert — ambiguity (x2) — as-built measurements positive numbers; no SOD on as-built review (no submitter identity captured) — `implementation/app.py:1392-1393,1454-1477`
- **§3.9** — revise — mismatch — `CLOSED` terminal only for the project's own transitions; other resources of a CLOSING/CLOSED project remain mutable (only condition creation checks project status) — `implementation/app.py:118-160` (only places with status gates besides condition create at `app.py:1534`)

**Notable genuine mismatches found and aligned:** the audit-coverage claim (largest deviation — many secondary mutations are unaudited), the posture invariant gap during MITIGATING, SOD placement after the from-state gate on all four review/confirm endpoints, the change-order review's pre-authentication body validation, and the unenforced "no further actions on a CLOSED project" claim.
