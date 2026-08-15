## Step 1: Create task directory — 2026-08-14T03:38:00.000Z

Pre-assigned directory tasks/task_1633_aggregate_quarry_crushed_stone_operations/ with workspace/ subdirectory already existed; treated as DONE per orchestrator instructions. No other task_* directory was created or written into.

## Step 2: Generate scaffold — 2026-08-14T04:54:47.841Z

Generation complete and lint-clean. Summary of what was produced for task_1633 (aggregate quarry & crushed-stone operations):

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1633_aggregate_quarry_crushed_stone_operations/`)
- `SCAFFOLD.yaml` (1576 lines) — §1.0–§1.7 only, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (942 lines) — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (1612 lines) — single top key `scaffold_corner_design`

**Key counts**
- Entities: 20 (QuarrySite posture root; Bench, ShotPlan, Muckpile, ProductSpec, Stockpile, GradationTest, Scale, ScaleCalibration, PlantRun, FreightZone, SalesOrder, ScaleTicket, RoyaltyAgreement, RoyaltyStatement, MshaInspection, MshaCitation, TrainingRecord, ReclamationBond, TruckQueueEntry)
- State machines: 19 entries / 73 transitions, incl. cyclic (ShotPlan redrill loop, Stockpile quarantine cycle), parallel dimensions (PlantRun production × reconciliation), fork-join (SalesOrder CONFIRMED/BACKORDERED branch), and derived posture on QuarrySite
- Calculations: 14 (dual-variant blast tonnage and royalty, tiered delivered pricing with pinned rounding order, phased bond requirement with pinned circular-evaluation order, FIFO allocation sweep selector, certification windows, etc.)
- Validations: 12 priority rows (auth → request → existence → state → posture → safety → temporal → referential → constraint → fiscal → OCC)
- Endpoints: 104 (flat topology, filtered-list FK reverse reachability everywhere, plus `POST /_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default)
- Errors: 39, all referenced by §1.2/§1.4 and covered by a test or stub
- Roles: 9, all `opaque`, segregation-of-duties enforced by X-User-ID comparison on approve/confirm/issue
- §1.8: 24 instances across all 9 rules (2 dual-variant, 3 combinatorial covering modes a/b/c, 3 non-linear machines, 2 cascades depth-3 and depth-2, 2 priority pairs state-vs-fiscal and safety-vs-temporal, 3 boundary, 3 cross-entity, 3 temporal-overlap with distinct interval semantics, 3 compensating invariants)
- §1.9: 69 active instances + 18 `excluded_because` stubs across all nine guide sections

**Verification**
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (1032 calls scanned)
- Additional scripted audits: zero unbound `${var}` placeholders, all instance names unique across both design files, all `grounds:` refs resolve, all stub targets exist, no forbidden concurrency vocabulary, and every pinned numeric literal (3792.6 t blast estimate, 19.31 delivered unit price, 13.30 vs 13.00 royalty variant delta, 10.02 per-ticket-rounding sum, 78000/48000 bond figures, 0.52 penalty, 62.0/65.0 yield variance, etc.) was computed and machine-verified.

**Notable design decisions**
- Posture-driven gating as primary archetype with quota/allocation secondary: an overdue S&S MSHA citation suspends the site, which auto-holds RELEASED benches and their live shot plans (depth-3 cascade with `MSHA_SUSPENSION`-scoped auto-resume that leaves manual holds sticky).
- Royalty ledger uses statement-based YTD accumulation with chronological-generation and half-open-period-overlap bans, giving an honest provisional-vs-final dual variant.
- Three OCC rules, each passing the serial-observability filter (stockpile adjustment, order reprice, bond release); I deliberately dropped an agreement-amendment OCC rule mid-design because the SUPERSEDED state check makes it a state precondition, not a true race — amendment supersession is handled by the state machine instead.
- I did not read any sibling task directory; the scaffold was derived solely from the scenario text and the skill specification.

## Step 3: Copy shared files — 2026-08-14T04:54:47.841Z

Copied ./INSTRUCTION.md to tasks/task_1633_aggregate_quarry_crushed_stone_operations/workspace/INSTRUCTION.md.
## Step 4: Generate PRD — 2026-08-14T05:14:00.000Z

All checks pass. The PRD is complete and shipped.

## Generation Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1633_aggregate_quarry_crushed_stone_operations/workspace/PRD.md` — 390 lines, 9,718 words, 69,163 bytes. The forbidden difficulty/corner design files were never opened or referenced.

### Structure
- **§1 Introduction** — 2 paragraphs (business context + the two organizing ideas: derived site posture, exact tonnage/money accounting; flat-topology note).
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (all 9 roles named, each `identity: opaque` translated individually, `miner_user_id` matching exception called out), 2.2 response envelope (**byte-verbatim** from `section-2.2-response-structure.md`, verified programmatically), 2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields), plus domain-derived 2.4 Logical Clock (default `2026-08-01T00:00:00Z`, no wall-clock fallback), 2.5 Common Resource Properties, 2.6 Units/Precision/Rounding, 2.7 Validation Order (full 12-tier chain with first-failure semantics), 2.8 OCC (3 rules, stale-version framing only), 2.9 Derived Posture & Cascading Consistency, 2.10 Segregation of Duties.
- **§3 Business Logic** — 9 business-process subsections: site/bonding/posture, bench lifecycle, drill-and-blast, specs/stockpiles/QC, plant runs, freight/orders, scale-house ops, royalty, MSHA compliance.
- **§4** — 104/104 endpoints, 4 columns only; roles verified against scaffold per-endpoint.
- **§5** — 39/39 error IDs with catalog-exact HTTP statuses, 2 columns only.

### Hard Contract Reports
```
Field coverage check:
- entities[].fields (+common): 134 required, 134 present, 0 missing
- endpoints[].request_body: 79 required, 79 present, 0 missing
- endpoints[].query_params: 24 required, 24 present, 0 missing
- endpoints[].path_params: 0 non-'id' params; all collection paths flat
Status: PASS

Rule coverage check:
- validation priority tiers: 12 checked, 12 expressed as an ordered chain with first-failure rule, 0 missing
- concurrency_rules OCC: 3 checked, 3 expressed (write endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 each), 0 missing
- state-machine transitions: 73 checked (incl. all sibling cancel/release/void branches and system cascades), 73 expressed, 0 missing
- calculations: 12 checked (blast tonnage dual-variant, muckpile drawdown, delivered-price 6-step pinned order, royalty provisional/final with per-ticket rounding, availability+FIFO sweep, phased bond, circuit yield 6-cell design table, net tons/tare variance, gradation inclusive bands, 30-day/5% penalty, queue selector, training currency, 180-day certification window, posture derivation), 12 fully expressed in operator-free prose, 0 missing
- validation conditions: all matchable to error_ids in §2/§3 narrative; all 39 error IDs present in §2/§3, 0 missing
- endpoint side_effects / applies_to: expressed in workflow narratives (fire→muckpile, run-complete 4-way cascade, ticket void compensation + statement lock, citation→posture→hold/resume cascade, amendment create-with-supersede), 0 missing
- field structured content (defaults, enums, 74/74 state/enum tokens present verbatim), 0 missing
- sibling-branch symmetry: cancel-from-4-states, bond-release 4 branches, gradation PASS/FAIL and void re-evaluation, reconcile RECONCILED/DISPUTED threshold branch — equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 803
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
Additional hygiene: zero pseudocode operators (`>=`, `==`, `min()`, arrows) in prose; zero fuzzy hedging words; zero paragraphs starting "The system".

### Notable decisions
- **Scattering strategy**: firing gates split across §3.3 (bench/posture/window) and §3.9 (training currency); weigh-out gates split across §3.7 (tare/overweight), §3.6 (over-shipment/fulfillment), and §3.8 (royalty accrual); the allocation sweep is defined in §3.6 but triggered from §3.4 (adjustments) and §3.5 (run completion); the `MSHA_SUSPENSION` sentinel cascade is specified once in §3.9 and cross-referenced from §§3.1–3.3.
- **Scaffold-ambiguity fidelity**: §1.2 lists posture preconditions on some shot-plan transitions (approve, start-drilling, redrill, fire) but not on complete-drilling/load; §3.3 mirrors the per-transition tables exactly, while §2.7 tier 6 mirrors §1.4's `applies_to` enumeration verbatim — no reconciliation invented.
- **Constants embedded in business prose** with unit framing (2,000 lbs/ton, 27 ft³/yd³, 1.6 t/yd³ density, 08:00–17:00 UTC blast window, 30-minute circuit cooldown, 110% over-shipment bound, 2.00% tare tolerance, 0.25% calibration tolerance).
- **"All roles"** in §4 for the nine-role GET endpoints, defined in the §4 preamble sentence.
## Step 6: Generate implementation — 2026-08-14T05:35:00.000Z

Done. Summary of the work:

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1633_aggregate_quarry_crushed_stone_operations/workspace/implementation/`)

- **`start.sh`** — executable launcher: guards the pip install behind `python3 -c "import flask"` (no-op on per-test reboots), then `exec python3 app.py` in the foreground.
- **`requirements.txt`** — `flask>=3.0`.
- **`app.py`** — Flask entry point; registers blueprints, maps `ApiError` to the error envelope, binds `0.0.0.0:$PORT` (default 10000), `threaded=True`.
- **`db.py`** — `Store` class with 20 entity dicts + logical clock initialized to exactly `2026-08-01T00:00:00Z`. No seeding anywhere; store starts empty every boot.
- **`errors.py`** — `ApiError` plus a factory per all 40 scaffold error IDs with their exact HTTP statuses.
- **`core.py`** — envelope helpers (`meta` with `api_request_id` = `req_` + 20 alnum chars, wall-clock `api_request_timestamp` with 3 fractional digits), `response_type`/`data` envelope, pagination (`limit` default 10/min 1/max 100, `offset` default 0; `total_count`, `has_more` in `meta` for lists), auth (tier 1: `X-User-Role` ∈ 9 declared roles and non-empty `X-User-ID` → `ERR_UNAUTHENTICATED`; tier 2: role-in-endpoint-list → `ERR_FORBIDDEN`), `created_at`-ASC list sorting, `touch()` (bumps `updated_at` + `version` on every mutation including cascades).
- **`services.py`** — Decimal/HALF_UP math helpers, `recompute_site` (pinned 4-step posture derivation + SUSPENDED enter/leave cascades with `MSHA_SUSPENSION` sentinel), stockpile invariant + latest-confirmed quarantine selector (max `sampled_at`, tie max `created_at`), strict-FIFO backorder allocation sweep (created_at ASC → quantity ASC → customer ASC, stop at first non-fit), scale certification windows (PASS → `calibrated_on`+180d), `compute_quote` (volume factor → freight → surcharge tiers, round-per-component-then-sum), active-agreement coverage lookup.
- **`routes_core.py`** — clock, sites, benches (release gates in tier order: state → posture OPERATING → elevation sequence → permit acreage), shot plans (full lifecycle, SoD on approve, training + [8,17) UTC blast window on fire, 1:1 muckpile creation), muckpiles, product specs, stockpiles (OCC-guarded adjustments with sweep on positive delta), gradation tests (exact-sieve-cover validation, inclusive PASS bands, SoD on confirm), scales/calibrations, plant runs (dual status dimensions, 3% output balance, 30-min circuit cooldown, 2% reconcile tolerance branch to DISPUTED, void reversal with `ERR_REVERSAL_BLOCKED`).
- **`routes_commerce.py`** — freight zones, sales orders (quote/confirm pin/backorder branch/cancel compensation per state/OCC reprice), truck queue (one-active-entry-per-truck, priority+queued_at+truck_id dispatch selector), scale tickets (weigh-in gates, tare-variance 2% with override, payload legality, royalty coverage, 110% over-shipment guard, full cascade on weigh-out and compensating void with statement-lock check), royalty agreements (one-ACTIVE-per-site, create-with-supersede amendments), royalty statements (half-open periods, overlap + chronological checks, per-ticket marginal-tier rounding then sum, YTD from prior non-VOID statements, SoD on issue, 5% late penalty after `due_on` = `issued_on`+30d), MSHA inspections/citations, training records (+12-month expiry, inclusive currency), reclamation bonds (OCC-guarded releases with post-release coverage check, PARTIALLY/FULLY_RELEASED boundary at equality).

## Boot verification

Actually launched via `bash start.sh` three times (ports 18233/18399/18400): server responds within ~2.5s, binds 0.0.0.0, honors `PORT`. Fresh-boot contract verified — after kill and relaunch, `/sites` returns `total_count: 0` and the logical clock is back at `2026-08-01T00:00:00Z` (confirmed via a training record whose `expires_on == 2026-08-01` reporting `is_current: true`). An 81-check end-to-end smoke suite exercising every workflow family (auth/RBAC, envelope, bench sequence + posture gates, bond OCC/coverage, shot-plan lifecycle through firing, quarantine selector, calibration windows, plant-run yield/reconcile, delivered-price quote arithmetic, backorder sweep, ticket weigh-out cascade, statement generation/penalty/lock, SUSPENDED hold/resume cascade, pagination) passed with zero failures.

## Notable design decisions

- **Validation tier ordering** implemented per §2.7: auth → RBAC → request shape → FK existence (left-to-right) → own-state → posture → safety → temporal → cross-entity → uniqueness/balance → fiscal → OCC last (412 only after all business checks pass).
- **All money/tonnage math in `Decimal` with `ROUND_HALF_UP`** at the scaffold's per-field precision (money 2dp, tons 3dp, blast tonnage/acreage 1dp, yield percents 1dp, tare variance 2dp).
- **Pre-transition posture guard** for complete-reclamation (evaluate guard against posture in force before the commit, then recompute) — the circular-misreading case the PRD calls out.
- **Statement chronological check** rejects a new `period_start` earlier than any existing non-VOID `period_end` (checked after the half-open overlap check, per the PRD's two-error distinction).
- **Scale certification on FAIL-create/void** recomputes from the latest remaining non-VOIDED PASS; a latest-event FAIL forces OUT_OF_SERVICE even if older PASSes exist (per the state machine's FAIL transition).
- No test suite exists yet in the task directory (`tests/` is generated by a separate pipeline step), so validation was via the smoke suite; the implementation is ready for `prd-bench-local-run --isolation per-test-server` once tests are generated.
## Step 5: Generate unit tests — 2026-08-14T06:05:00.000Z

(Note: the subagent's first run stopped mid-generation after test_03; it was resumed via SendMessage with its context intact and completed the remaining files plus Stage 2 self-checks. The summary below is its final exit report.)

All self-checks pass. Generation complete.

## Exit Summary

**Helper infrastructure created** (`/home/ubuntu/github/CodingPRD/tasks/task_1633_aggregate_quarry_crushed_stone_operations/test_helpers/`):
- `types.py` — 20 entity TypedDicts + 20 status/role enums (all entities carry id/created_at/updated_at/version per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (~75 methods, incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 40 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + `assert_stockpile_invariants`
- `factories.py` — payload factories per entity
- `constants.py` — PRD thresholds (0.25 calibration tolerance, 180-day window, 3%/2% balances, 110% over-shipment, pricing tiers, blast window, clock default)
- `test_users.py` — 9 opaque role header constants + per-user builders for SoD tests
- `fixtures.py` — composite chains: `setup_blast_site` (site→bond→bench→plan→FIRED→muckpile), `setup_plant_run_site`, `setup_ticketing_site`, `complete_ticket`, run lifecycle helpers

**Test suite** (`test_suite/`): `conftest.py` + 8 files, **116 tests collected, 0 collection errors**.

**Queue A (Difficulty) — 48 tests**: all 24 instances covered by exactly ≥2 tests each.

**Queue B (Corner) — 68 tests**: 68/69 non-stub instances covered; all 18 `excluded_because:` stubs left untranslated (every `difficulty_instance` cross-reference verified to resolve).

**Instances skipped with reason** (1):
- `Corner/entities/site_create_posture_input_ignored` — fails the PRD-first two-condition filter: PRD §3.1 says `posture` is "computed rather than stored from input" but never states that a client-supplied computed field in the create body is silently *ignored* rather than rejected as an invalid request; two faithful PRD-only implementers could legitimately ship either behavior. Gap left as a gap (no placeholder, no skip marker).

**Stage 2 self-checks**:
- Tag audit: 116/116 tests carry exactly one `Design:` line; all resolve to real instances; none point at stubs.
- Coverage: every difficulty instance ≥2 tests; every non-stub corner instance ≥1 (except the documented skip).
- PRD citation pass: 144 quoted citation spans — all survive verbatim grep of `workspace/PRD.md` (one ellipsis-spliced paraphrase found and rewritten to the full verbatim tier-4 sentence).
- No `pytest.mark.skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; `python3 -m py_compile` clean; `pytest --collect-only` collects 116 with no errors.
## Step 7: Run tests and iterate — 2026-08-14T06:20:00.000Z

All 8 rounds pass cleanly: 116/116 in every round. Exiting with the summary.

## Summary

**Iterations run**: 2 (sweep 1 surfaced the flaky test; sweep 2 after the fix: all 8 rounds passed 116/116).

**Tests deleted**: none.

**Fixes applied to `test_helpers/`**: none.

**Fixes applied to `implementation/`**: none.

**Fixes applied to `test_suite/`**: 1

- **File**: `/home/ubuntu/github/CodingPRD/tasks/task_1633_aggregate_quarry_crushed_stone_operations/test_suite/test_08_api_conventions_rbac.py`
- **Test**: `TestPagination::test_pagination_limit_offset_with_filter`
- **Failure mode**: flaky — failed in rounds 1, 2, 3, 4, 8; passed in rounds 5, 6, 7 (a 5/8 vs 3/8 split, consistent with a 1/3 probability).
- **Root cause (STEP 2, test-vs-PRD consistency)**: The test created three benches with the logical clock frozen at startup. Per PRD §2.4 the logical clock is "the sole source of 'now' for ... every recorded timestamp", so all three benches necessarily shared the identical `created_at` (`2026-08-01T00:00:00.000Z`). PRD §2.3 requires sorting "by `created_at` in ascending order" but is silent on tie-breaking among equal keys. The implementation tie-breaks on random UUID, so the assertion `data[0]["id"] == b3["id"]` at offset 2 held only when b3 happened to draw the largest UUID. The test's setup constructed a precondition under which the PRD rule does not uniquely determine the asserted outcome.
- **Fix**: Added `set_clock` to the test's imports and advanced the logical clock by one minute between the three bench creations, making `created_at` strictly increasing. The PRD §2.3 created_at-ascending rule then uniquely determines the full ordering ([b1, b2, b3]), so the last-created bench deterministically lands on page 2 at offset 2. All original assertions (limit/offset/total_count/has_more and the b3-at-offset-2 ordering check) were preserved — the test became more faithful to PRD, not weaker.
## Step 8: Finalize PRD — 2026-08-14T06:30:00.000Z

Done. One minimal inline edit, exactly tracing the single step_7_diff item.

## Summary

**Line counts / %-delta:** PRD.md = 390 lines; PRD_FINALIZED.md = 390 lines; delta = 0 lines (0.0%). Single-sentence inline revision within existing line 70; no sections added.

**Changes:**
- §2.3 (Pagination) — **revise** — Extended the default list-sort sentence to pin the tie-break the implementation exhibits: "...sorted by `created_at` in ascending order, with ties among equal `created_at` values broken by `id` in ascending string order." — `implementation/core.py:145` (`items.sort(key=lambda it: (it.get("created_at", ""), it.get("id", "")))` in `list_response`, the shared helper for 19 list endpoints) and `implementation/routes_commerce.py:1003` (`items.sort(key=lambda r: (r["created_at"], r["id"]))` in the custom `list_training` endpoint). `id` is a server-minted UUID (`core.py:51,161`), so string ordering is well-defined.

**Per-edit pre-edit search log:**

- **Edit 1 (§2.3 tie-break):**
  - (a) **Subject:** default ordering rule for list-endpoint responses — tie-breaking among equal `created_at` keys.
  - (b) **Impl paths enumerated:** `core.py:137-149` (`list_response`, used by all standard lists — verified callsites via grep: sites, benches, shot-plans, muckpiles, product-specs, stockpiles, gradation-tests, scales, scale-calibrations, plant-runs in `routes_core.py`; freight-zones, sales-orders, queue-entries, scale-tickets, royalty-agreements, royalty-statements, msha-inspections, msha-citations, reclamation-bonds in `routes_commerce.py`); `routes_commerce.py:991-1008` (`list_training`, custom but identical `(created_at, id)` key); plus the three domain-specific sorts that the PRD already pins elsewhere and which this edit deliberately does NOT touch — `services.py:211` (backorder FIFO sweep, pinned by §3.6), `routes_commerce.py:335` (dispatch selector, pinned by §3.7), `routes_commerce.py:704,716` (statement sweep, pinned by §3.8).
  - (c) **Wording adjustment:** scoped the clause to the existing "every list endpoint" sentence with "Unless otherwise specified" preserved, so §3.6/§3.7/§3.8's explicitly pinned orderings remain the "otherwise specified" exceptions; phrased the tie-break as "`id` in ascending string order" (matching the string-key lambda at both sites) rather than "UUID order" or "insertion order," avoiding any false universal claim about id generation or storage ordering.

No other edits were made: the step_7_diff lists zero implementation fixes, zero test deletions, and zero test_helper fixes — the sole test-suite fix was a fixture determinism repair (advancing the logical clock between bench creations), and the only PRD-side gap it revealed was the §2.3 tie-break silence now pinned.
## Step 9: Complete PRD — 2026-08-14T06:50:00.000Z

The diff is complete and correct — all edits are inline (line count unchanged at 390). Final statistics verified: PRD_FINALIZED.md = 69,247 chars, PRD_COMPLETED.md = 73,278 chars (+4,031).

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1633_aggregate_quarry_crushed_stone_operations/workspace/PRD_COMPLETED.md`
**Source:** `PRD_FINALIZED.md` (existed; copied, then edited in place)
**Line counts:** 390 → 390 (all changes inline; no new sections/paragraphs). **Char delta:** +4,031 (69,247 → 73,278)
**Counts:** 26 ambiguity-pins, 8 mismatch-revisions.

### Changes (one bullet each)

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned to server wall clock, explicitly not the logical clock — `implementation/core.py:31-34,55-59`
- §2.3 — insert — ambiguity — non-integer or out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` (400), not clamped — `implementation/core.py:110-134`
- §2.3 — revise — ambiguity — list filters pinned as equality match on the named field — `implementation/core.py:137-149`
- §2.4 — insert — ambiguity — clock-set capability returns 200 OK with `current_utc` data object — `implementation/routes_core.py:158-167`
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — `implementation/core.py:158-165`
- §2.7 intro — insert — mismatch — §3-enumerated gate sequences pinned as governing over the global tier ordering (resolves tier-list vs impl conflicts at weigh-out, run start, statement generation, shot-plan gates) — `implementation/routes_commerce.py:471-494`, `implementation/routes_core.py:1057-1084`, `implementation/routes_commerce.py:676-694`
- §2.7 tier 3 — insert — mismatch — sieve-coverage check runs only after the stockpile resolves — `implementation/routes_core.py:819-826`
- §2.7 tier 5 — insert — mismatch — six endpoints (adjustments, reprice, bond release, run complete, weigh-out, amendments) resolve path id before body validation; first five also evaluate own-state before request-shape — `implementation/routes_core.py:749-758,1091-1099`, `implementation/routes_commerce.py:250-257,449-456,1059-1067,615-624`
- §2.9 — revise — mismatch — posture recompute fires only on bench transitions that alter the disturbed set; manual hold/resume trigger none — `implementation/routes_core.py:298-333`
- §3.1 — revise — mismatch — same recompute-trigger correction in the pinned-order paragraph — `implementation/routes_core.py:298-333`
- §3.1 — insert — ambiguity — `release_amount_usd` exceeding remaining → `ERR_INVALID_REQUEST` (400); `FULLY_RELEASED` is terminal (`ERR_INVALID_STATE`) — `implementation/routes_commerce.py:1063-1071`
- §3.2 — insert — ambiguity — bench born `PLANNED` with `hold_reason` unset — `implementation/routes_core.py:230-240`
- §3.3 — insert — ambiguity — `hole_count` is an integer ≥1; plan born with `submitted_by_user_id`, `approved_by_user_id`, `fired_at`, `hold_return_state` unset — `implementation/routes_core.py:407-440`
- §3.3 — insert — ambiguity — `loaded_explosive_lbs` payload strictly positive — `implementation/routes_core.py:548`
- §3.4 — insert — ambiguity — duplicate `spec_code` → `ERR_INVALID_REQUEST` (400) — `implementation/routes_core.py:660-662`
- §3.4 — insert — ambiguity — stockpile uniqueness enforced regardless of existing pile's status (even `CLOSED` blocks) — `implementation/routes_core.py:713-715`
- §3.4 — insert — ambiguity — adjustments accepted on `OPEN` and `QUARANTINED`; `CLOSED` → `ERR_INVALID_STATE` — `implementation/routes_core.py:752-754`
- §3.4 — insert — ambiguity — gradation-test reporting permitted against a pile in any status — `implementation/routes_core.py:800-848`
- §3.5 — insert — ambiguity — run born with `started_at`/`ended_at`/`run_hours`/`input_tons`/`reconciled_input_tons`/`yield_summary` unset and `outputs` empty — `implementation/routes_core.py:1015-1032`
- §3.5 — revise — mismatch — output-row `stockpile_id`/`product_spec_id` resolve after balance and feed gates; per-row order pinned: site/spec match (`ERR_INVALID_REQUEST`) → `OPEN` → spec `ACTIVE` → capacity — `implementation/routes_core.py:1112-1136`
- §3.5 — insert — ambiguity — reconcile stores the submitted figure in both branches; a still-out-of-tolerance correction stays `DISPUTED`; `RECONCILED` rejects further reconciliation with `ERR_INVALID_STATE` — `implementation/routes_core.py:1186-1201`
- §3.6 — insert — ambiguity — duplicate `zone_code` → `ERR_INVALID_REQUEST` (400) — `implementation/routes_commerce.py:86-88`
- §3.6 — insert — ambiguity — reprice performs no specification- or zone-status re-check — `implementation/routes_commerce.py:250-266`
- §3.7 — insert — ambiguity — duplicate `scale_code` within a site → `ERR_INVALID_REQUEST` (400) — `implementation/routes_core.py:907-909`
- §3.7 — revise — mismatch — certification recomputation rewritten: latest non-voided calibration event (greatest `calibrated_on`, tie greatest `created_at`) decides service state; `certified_through` is latest non-voided PASS + 180 days, or unset when none remains — `implementation/services.py:233-267`
- §3.7 — insert — ambiguity — queue-entry states `EXITED` and `NO_SHOW` pinned terminal — `implementation/routes_commerce.py:354-373,519`
- §3.7 — revise — mismatch — weigh-in gate sequence pinned to impl order (entry `AT_SCALE_IN` → order `CONFIRMED`/`IN_FULFILLMENT` → posture → scale → stockpile), with previously unnamed error ids — `implementation/routes_commerce.py:388-402`
- §3.7 — insert — ambiguity — `allow_tare_variance` defaults to false when omitted — `implementation/routes_commerce.py:457-461`
- §3.7 — insert — ambiguity — statement-lock on ticket void uses the calendar date of `completed_at` within the half-open period — `implementation/routes_commerce.py:532-540`
- §3.8 — insert — ambiguity — `period_end` must be strictly after `period_start` (`ERR_INVALID_REQUEST`) — `implementation/routes_commerce.py:672-673`
- §3.8 — revise — ambiguity — statement period membership is by the calendar date of `completed_at` (not the timestamp) — `implementation/routes_commerce.py:714`, `implementation/services.py:332-334`
- §3.8 — insert — ambiguity — agreement coverage for statement generation tested at `period_start` — `implementation/routes_commerce.py:692`
- §3.8 — insert — ambiguity — amendment's new agreement inherits `site_id` and `landowner_name` from the superseded agreement — `implementation/routes_commerce.py:630-643`
- §3.9 — insert — ambiguity — `expires_on` is twelve calendar months after `completed_on` with day clamped to month end — `implementation/routes_commerce.py:954-961,975`

**Noted but deliberately not changed:** PRD tier 6 lists a posture gate on explosive loading that impl omits (`routes_core.py:544-558`) — unobservable, because a `SUSPENDED` site's cascade guarantees no `RELEASED` bench exists, so the bench-`RELEASED` check always fires first; behavior is equivalent. Unreachable defensive fallbacks (e.g., `hold_return_state or "APPROVED"`) and framework-level 404/405 handling were likewise left unpinned.
