# Worklog — task_2416_senior_living_dining_program_therapeutic_diets

## Step 1: Create task directory — 2026-09-02T15:42:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2416_senior_living_dining_program_therapeutic_diets` and its `workspace/` subdirectory. Index 2416 was pre-assigned by the caller; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T17:12:00.000Z

All three artifacts are complete and the linter is clean.

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_2416_senior_living_dining_program_therapeutic_diets/`

**`SCAFFOLD.yaml`** (§1.0–§1.7, no design keys; 2552 lines)
- `domain_name: senior-living-dining-therapeutic-diets`, `api_prefix: ""`, logical clock default `2026-08-01T00:00:00Z`
- complexity_profile: `expert_plus`, archetypes `temporal_windowing` / `compliance_audit`, topology `flat`, state-machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`
- **15 entities**: Community, DiningVenue, Resident, DietOrder, SubstitutionRule, SeatingReservation, MenuCycle, MenuItem, TherapeuticExtension, MealServiceTicket, BillingReconciliation, IntakeObservation, PlanOfCareReview, TemperatureLog, CommitteeFeedback
- **8 state machines** (DietOrder carries two independent axes `clinical_status` × `review_status`; TherapeuticExtension and MenuCycle are cyclic; venue posture ladder COMPLIANT/WATCH/SUSPENDED; PlanOfCareReview branches on three outcomes)
- **2 OCC rules** (`diet-order-create-stale-resident` on `expected_resident_version`, `reservation-create-stale-venue` on `expected_venue_version`), **13 calculations**, **31 ordered validations**, **57 endpoints** (27 GET / 30 POST), **41 errors**, **7 roles**

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 9 rules × 2 instances = **18**: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

**`SCAFFOLD_CORNER_DESIGN.yaml`** — **86 instances across all 9 sections**: entities 12, state_machines 18, calculations 13, validations 10, endpoints 5, errors 15, rbac 5, cross_cutting_layers 7, consistency_model 1. Nine of these are `excluded_because` stubs that delegate to a named §1.8 instance (no `test_recipe`); all other instances carry `grounds`, `distinguishing_aspect` and a full `test_recipe` with pre-computed literal asserts. Every error id in the catalog is reachable, including `ERR_OBSERVATION_NOT_FOUND` via the `trigger_observation_id` filter.

**Lint verdict** (`scaffold_lint.py`, verbatim):
```
Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  854

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes: instance names are unique across the union of both design files (86 + 18, no collisions); no forbidden concurrency vocabulary appears in any file; two §1.2-vs-§1.5 actor mismatches in SCAFFOLD.yaml were corrected (diet-order discontinue is `ClinicalStaff` only; therapeutic-extension submit is `RegisteredDietitian` only). No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-02T17:12:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T17:32:00.000Z

PRD generated and verified.

## Deliverable
`.../workspace/PRD.md` — **466 lines**, complete, ends at a real section boundary (final row of the §5 catalogue, `ERR_VARIANCE_UNRESOLVED | 409`; no audit footer, no truncation). The two withheld design files were never opened, grepped, or referenced.

## Section list
- **§1 Introduction** (3 paragraphs)
- **§2 Global Specifications & System-Wide Principles** (10 subsections): 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-verbatim, `diff` against `section-2.2-response-structure.md` exits 0) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Validation Precedence · 2.7 Community Boundaries and Linked-Resource Integrity · 2.8 Stale-Version Guards on Shared Parents · 2.9 Money, Percentages and Rounding Discipline · 2.10 Cascade Discipline and Derived Fields
- **§3 Business Logic & Workflows** (9 domain-derived subsections): 3.1 Program Setup: Communities, Venues and Resident Admission · 3.2 Diet Order Intake and the Parallel Review Axis · 3.3 Substitution Profiles and Tray-Card Resolution · 3.4 Menu Cycle Authoring, Therapeutic Extensions and the Committee Refresh Loop · 3.5 The Reservation Book: Spacing, Capacity, Waitlists and Seating · 3.6 Meal Tickets: Issuance, Pricing, Service and Voids · 3.7 Satellite Kitchen Temperature Compliance · 3.8 Intake Monitoring, Weight Trends and Plan-of-Care Review · 3.9 Meal-Count Reconciliation and Period Closure
- **§4 Endpoint Definitions** (status-code paragraph + 4-column table)
- **§5 Error Code Catalogue** (2-column table)

## Coverage counts (machine-verified against SCAFFOLD.yaml)
- **Endpoints: 57/57.** Method + path + authorized-role set compared row-by-row against the scaffold: 0 missing, 0 extra, **0 role mismatches**.
- **Errors: 41/41**, with **0 HTTP-status mismatches** against the scaffold's `http` values (incl. the outlier `ERR_SPONSOR_LIMIT_EXCEEDED` = 402 and `ERR_STALE_VERSION` = 412).
- 15 entities, 8 state machines (every from→to edge incl. system cascades), 13 calculations, 31 validation tiers, 2 OCC rules, 7 roles.

## Hard Contract reports
**Contract 1 — Field-Name Coverage: PASS.** Programmatic sweep (2 passes, fenced code blocks stripped so the §2.2 JSON fences don't skew backtick pairing): all **112/112** `entities[].fields[].name` and all **93/93** identifiers from `endpoints[].input`/`query_params`/`path_params`/`output` appear verbatim in backticks — 0 missing. First pass found one gap (`menu_item_id`), which was repaired in §3.4; re-run is clean. All 36 domain enum values also appear; the only scaffold UPPER_SNAKE tokens absent are the 34 *constant identifiers* (`MEALS_TAX_PCT`, `TEXTURE_RANK`, `POSTURE_WATCH_AT`, …), whose numeric values are all stated in prose as required.

**Contract 2 — Rule Coverage: PASS.** (1) All 31 validation priorities are stated as an explicit ordered ladder in §2.6 with tie-break notes (suspension before verified-order; spacing before capacity). (2) Both `concurrency_rules` are documented naming write operation + `expected_resident_version` / `expected_venue_version` + `ERR_STALE_VERSION` + 412, framed purely as stale-version rejection — no "simultaneously"/"race"/"first-writer-wins" anywhere in the file (grep-verified 0 hits), plus the version-bump provenance that makes each guard bite. (3) Every cross-entity cascade is spelled out with all secondary effects, including the 4-hop intake chain, the 3-hop void chain, the temperature-suspension hold chain, publish→archive→`active_menu_cycle_id`, refresh→ballot-acknowledge + extension-retire→coverage recompute, and finalize→SERVED-to-BILLED. Every `side_effects` entry of all 30 write endpoints was diffed against the scaffold. (4) Full `applies_to` endpoint sets are given for each scoped validation (e.g. `ERR_RESIDENT_NOT_ACTIVE` across all six contexts with the `ON_LEAVE` vs `DISCHARGED` split; `ERR_DIET_ORDER_NOT_VERIFIED` across all four). (5) Field-level structure — types, ranges, defaults (`limit` 10/1/100, cap 20000, tolerance 5000, turn 60, buffer 20), initial values, and the three `common_fields: false` records (`IntakeObservation`, `TemperatureLog`, `CommitteeFeedback`: `id` + `created_at` only, no `updated_at`, no `version`) — is stated explicitly. (6) Sibling branches carry equal density: both diet-order review decisions and both source states, all three plan-of-care outcomes, both weight variants, both reconciliation variants, all three posture edges incl. the sticky-counter no-op. Tail: all 13 calculations carry full formulas, constants, pinned evaluation order, precision and round-half-up rules translated into prose, including both scaffold worked pins (sponsored TAKEOUT/DINNER → 1549 vs. the wrong 1548; pre-fee base 3386 → 3589 vs. the wrong 3538), the half-open venue interval vs. closed 90-minute resident interval, and the tier keyed on `pre_fee_base_cents`.

**Contract 3 — §3 Path Purity: PASS.** Of the backticked tokens inside §3, **0** begin with `/`, are a bare HTTP method, or combine method+path.

**Orchestrator verification:** independently confirmed `wc -l` = 466, tail ends on a complete table row of §5 (a real section boundary, not mid-sentence), 5 top-level `##` sections, 41 unique `ERR_*` ids. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T18:40:00.000Z

Suite is complete and audited.

## Files written

`test_helpers/` (Stage 1, 9 modules): `__init__.py`, `types.py`, `api_client.py` (57 methods, one per PRD endpoint), `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`
`test_suite/` (Stage 2): `conftest.py` + `test_01` … `test_15` (15 test modules)
Total 7,842 lines. `workspace/implementation/` was never read or touched.

## Test counts

**99 tests collected, 0 collection errors** (`PYTHONPATH=. pytest test_suite --collect-only -q`).

Queue A (Difficulty) — 36 tests / 18 instances, exactly 2 per instance across all 9 rules (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`):
test_01 reconciliation 8 · test_02 intake monitoring 8 · test_03 reservation intervals 12 · test_04 ticket pricing/posture 6 · test_05 extension review rounds 2

Queue B (Corner) — 63 tests / 63 non-stub instances, 1 each:
entities 12 (test_06) · state_machines 12 (test_07 6, test_08 6) · calculations 7 (test_09) · validations 7 (test_10) · endpoints 5 (test_11) · errors 10 (test_12) · rbac 5 (test_13) · cross_cutting_layers 4 (test_14) · consistency_model 1 (test_15)

## Coverage audit (scripted, all green)

- Every one of 99 tests carries exactly one `Design:` line, and it is the last docstring line. Zero untagged, zero dual-tagged.
- Every tag resolves to a real instance `name:` in the source yaml; no tag points at a stub.
- 18/18 difficulty instances have >=2 tests; 63/63 non-stub corner instances have >=1 test.
- All 23 corner stubs left untranslated; each one's `excluded_because` was verified to name a real difficulty instance (the cross-reference lives in that prose field, not a `difficulty_instance` key).
- Citation pass: all 99 `PRD: "…"` quotes now survive a whitespace-normalized verbatim grep against `workspace/PRD.md`, each >=8 words and a complete unabbreviated sentence. This pass caught and I fixed 7 docstrings that had truncated a PRD sentence mid-clause and closed it with an invented period (test_03, test_06, test_09, test_10 x3, test_13).
- No `skip`/`skipif`/`xfail`/`TODO`/placeholder anywhere; the word "scaffold" and scaffold section references absent from all generated code (only PRD `§` references appear, in helper comments).
- pyflakes clean on `test_suite` and `test_helpers` (no undefined names, no unused imports outside the intentional `__init__.py` re-exports); every `api.<method>` used exists on `ApiClient`.

## Skipped instances / deliberate omissions

- 23 corner stubs (`excluded_because` present) never translated, per the two-queue rule: state_machines 6, calculations 6, errors 5, validations 3, cross_cutting_layers 3.
- Two probes dropped from `Corner/errors/not_found_family_each_entity_returns_its_own_id` for failing unique-derivability: (a) the `trigger_observation_id` **query-filter** 404 — PRD tier 5 scopes body-reference checks to "every foreign key supplied in the payload", so 404-vs-empty-list for a filter is ambiguous; (b) the `POST /menu-cycles/{ghost}/committee-feedback` "path before body" probe — tier 2 requires a `ResidentRepresentative` to be addressing its own resident, which can fire `ERR_FORBIDDEN_ROLE` before tier 4.
- One secondary assertion dropped from `Difficulty/transitive_cascade/weight_trend_out_of_order_observation_dates_still_chronological` (`tray_state == HOLD_PENDING_REVIEW`, not PRD-derivable).

## Design literals overridden by PRD-derived values

- `Corner/rbac/both_dsm_and_satellite_lead_can_issue_tickets`: instance said a sponsored TAKEOUT LUNCH bills 900 ("base 850 + 50 packaging"). PRD §3.6 gives base 1100 → discount 138 → subtotal 1137 → tax 82 → **1219** asserted.
- `Corner/rbac/dietitian_cannot_review_own_therapeutic_extension`: instance said `extension_coverage_status == "COVERED"`; the PRD enum value is **`COMPLETE`**.

No pytest execution against a live server was performed (implementation is being generated concurrently); verification here is collection + static + citation auditing.

## Step 6: Generate implementation — 2026-09-02T18:40:30.000Z

Implementation complete and smoke-verified.

## Files written
`.../workspace/implementation/`

**Core (10 files):** `app.py`, `start.sh`, `requirements.txt` (Flask==3.0.3), `clock.py`, `errors.py`, `db.py`, `response.py`, `constants.py`, `shape.py`, `auth.py`, `serialize.py`

**`services/`:** `__init__.py`, `calc.py` (all pinned calculations: ticket pricing, weight trends, risk score, interval geometry, temperature posture, refresh index, meal-count reconciliation + fee waterfall), `derive.py` (derived fields, cascades, tray-card resolution, waitlist promotion, period-closure lookups)

**`routes/`:** `__init__.py`, `common.py`, `communities.py`, `venues.py`, `residents.py`, `diet_orders.py`, `reservations.py`, `menus.py`, `tickets.py`, `reconciliations.py`, `reviews.py`, `clock_ctl.py`

## Endpoint count
**57 routes registered — 27 GET + 30 POST**, exactly matching the PRD §4 table (verified by enumerating `app.url_map`).

## Launcher
`start.sh` is `set -euo pipefail`, `cd`s to its own directory, installs Flask **only when the import fails** (avoids pip contention across the 8 concurrent per-test reboots), and ends with `exec python3 app.py`. `app.py` runs `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","8000")), threaded=True, use_reloader=False)` — **binds 0.0.0.0 on $PORT in the foreground**. Confirmed live: `PORT=18416 ./start.sh` listened on `0.0.0.0:18416` and answered a real `curl` POST/GET.

## Storage
In-memory only — a single `Store` object of 15 empty dicts keyed by id. No SQLite, no JSON dump, no `/tmp` cache, zero seeded/preloaded/hardcoded entities; a fresh boot answers `GET /communities/{id}` with 404 and the logical clock reads exactly `2026-08-01T00:00:00.000Z`.

## Smoke test (all green, then torn down)
Full happy path plus negatives: clock set (verbatim echo) → community → venue → resident → diet order → dietitian APPROVE (parallel axes to ACTIVE/APPROVED) → cycle → item (day_index-range 400, duplicate-code 409) → extension submit/SoD-403/approve → coverage COMPLETE → submit → publish → `active_menu_cycle_id` → tray card → reservation (`seat_end_utc` computed, meal-spacing 409) → seat (cascade RESIDENT ticket at 650) → seat-availability roll-up → **sponsored TAKEOUT DINNER priced 1549** (the component-rounding pin) → serve (reservation → COMPLETED) → reconciliation (ledger 2199 / census 2199 / fee 132 / net 2331) → finalize (tickets → BILLED) → `ERR_PERIOD_CLOSED` → temperature ladder to SUSPENDED and corrective recovery to index 0 → intake cascade hops 1–4 (`rolling_30d = -11.43`, `risk_score = 95.00`, `tray_card_state = HOLD_PENDING_REVIEW`, review opened `LOW_INTAKE_AVG` with `risk_score_at_open 55.00`) → review SoD 403 → ESCALATED → tray BLOCKED → ballot (`vote_weight` 2, index 200.00/QUORUM, auto PUBLISHED→REFRESH_PENDING) → duplicate-ballot 409 → refresh (round 1, extensions RETIRED, coverage back to INCOMPLETE) → RBAC/401/403/404/pagination-bound 400s and unknown-path 404 in envelope form.

`pyflakes` reports the whole tree clean; no stray processes or `__pycache__` left behind.

## Step 7: Run tests and iterate — 2026-09-02T18:46:00.000Z

Clean sweep on the first iteration — no fixes were needed.

## Summary

**Iterations run:** 1

**Sweep result:** All 8 parallel rounds passed **99/99** (`passed=99, failed=0, errors=0, skipped=0`) with zero flakiness across rounds. Per-round wall time ~173s under `--isolation per-test-server`. `sweep.log` contains exactly 8 `Results: 99/99 passed` lines and zero `Terminated` occurrences, confirming the sweep ran to completion under `setsid` and was not reaped.

**Tests deleted:** none — no test failed in any round, so the diagnostic protocol (STEP 0 union set) was empty and no PRD coverage / unique-derivability adjudication was required.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `workspace/implementation/`:** none.

**Artifacts left in place:**
- `workspace/implementation/results.1.json` … `results.8.json` (the passing sweep)
- `workspace/sweep.log`

Note for the caller: the host had ~33 concurrent `prd-bench-local-run` processes during the sweep (other pipelines), so this clean 8/8 was achieved under realistic CPU contention — the pass is not an artifact of an idle machine. The 99-test suite (Queue A difficulty 36 + Queue B corner 63) exercises the OCC stale-version guards, the dual-variant reconciliation/weight calculations, and the parallel DietOrder state axes, all of which are the timing-sensitive areas the 8-round sweep is designed to surface; none showed round-to-round variance.

**Orchestrator verification (per the known failure mode where a Step 7 agent claims a clean sweep with no artifacts):** independently confirmed on disk — all 8 `results.{1..8}.json` exist (~30 KB each, mtime 18:39, i.e. this run), each parses with `passed=99 total=99 failed=0`; `sweep.log` has 16 lines matching `passed` (the 8 per-round pytest lines plus the 8 runner `Results:` lines) and 0 lines matching `Terminated`. Claim substantiated.

## Step 8: Finalize PRD — 2026-09-02T18:46:30.000Z

**SKIPPED per the skill's explicit skip condition.** Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the test suite exercised, there is no `<step_7_diff>` to hand off, and no finalizer subagent was spawned. `workspace/PRD_FINALIZED.md` is intentionally absent; Step 9 will start from `workspace/PRD.md`.

Orchestrator decision rationale (recorded because this pipeline is non-interactive): the skip condition is stated unconditionally in the skill and all four fix counts are zero and independently verified above, so no judgement call was required. Residual PRD silences that the test suite never asserted are exactly what Step 9's full implementation scan exists to close.

## Step 9: Complete PRD — 2026-09-02T18:58:00.000Z

Verification done. `PRD_COMPLETED.md` exists, is 466 lines (identical structure to source — every change is in-paragraph), ends at the real §5 boundary with `| ERR_VARIANCE_UNRESOLVED | 409 |`, no truncation.

## Counts

- **Source** `workspace/PRD.md`: 466 lines / 96,466 chars
- **Output** `workspace/PRD_COMPLETED.md`: 466 lines / 103,798 chars → **+7,332 chars**, 0 line delta (33 lines revised in place, no new sections, no new paragraphs)
- **32 changes**: **21 ambiguity-pins**, **11 mismatch-revisions**

## Changes

- §2.1 — insert — ambiguity — indirect-ownership resolves 404 before 403; payload-resident ownership checked only once the resident row is read; RR list reads are implicitly scoped and a foreign explicit `resident_id` filter is `ERR_FORBIDDEN_ROLE` rather than an empty page — `implementation/auth.py:36-44`, `routes/reviews.py:35-44`, `routes/reservations.py:40-49`
- §2.3 — insert — ambiguity — computed-read query params validated only after the path id resolves; malformed filter values are `ERR_INVALID_REQUEST`; an unresolvable id filter matches nothing rather than erroring — `routes/residents.py:94-96`, `routes/venues.py:48-50`, `shape.py:239-281`
- §2.4 — revise — mismatch — a recompute that lands on the already-stored value moves neither `updated_at` nor `version` — `db.py:68-73`
- §2.5 — insert — ambiguity — the clock endpoint echoes the supplied `current_utc` representation verbatim, not a normalized one — `routes/clock_ctl.py:19-20`
- §2.6 tier 3 — revise — mismatch — declared decimal precision is a ceiling (fewer places accepted, more rejected); query-string and cycle-dependent bounds are checked after the tier, not in it — `shape.py:100-110`, `routes/menus.py:132-138`
- §2.6 tier 12 — revise — mismatch — ticket service reads only the posture half of the tier and ignores venue `status` — `routes/tickets.py:170-175`
- §2.7 — insert — ambiguity — `trigger_observation_id` is never client-supplied; it is always the cascade's own observation — `routes/residents.py:251-262`
- §2.9 — insert — ambiguity — input precision is a ceiling for all money/decimal fields — `shape.py:100-110`
- §2.10 — revise — mismatch — `active_menu_cycle_id` is re-evaluated on every read (pure function of the clock date), so advancing the clock past `effective_end_date` empties it with no write — `services/derive.py`, `serialize.py`
- §3.1 — revise — mismatch — `baseline_weight_kg` accepts at most 1 decimal place — `routes/residents.py:107`
- §3.1 — revise — mismatch — sponsorship is not gated on the sponsor's `dining_status`; a non-ACTIVE sponsor still gets a ticket, just without the discount — `routes/tickets.py:104-139`, `services/calc.py:39-46`
- §3.2 — insert — ambiguity — superseding a non-ACTIVE predecessor is `ERR_INVALID_STATE` — `routes/diet_orders.py:100-104`
- §3.2 — insert — ambiguity — `reviewer_note` is stored on APPROVE only when supplied, but always overwritten on REQUEST_CHANGES — `routes/diet_orders.py:146,172-173,193`
- §3.2 — insert — ambiguity — the clinical axis moves only out of `PENDING_REVIEW` — `routes/diet_orders.py:175-177`
- §3.2 — insert — ambiguity — every APPROVE recomputes the risk score, and `tray_card_state` clears only from the HOLD value — `routes/diet_orders.py:185-188`
- §3.2 — insert — ambiguity — the discontinue `reason` is accepted but not persisted — `routes/diet_orders.py:237`
- §3.3 — insert — ambiguity — each tray-card line also carries `menu_item_id`, `item_code`, `name`, `base_texture`, `served_item_code`, `substitution_rule_id`, `reason` — `services/derive.py:248-256`
- §3.4 — insert — ambiguity — adding a menu item is ungated by cycle status — `routes/menus.py:118-160`
- §3.4 — insert — ambiguity — extension authoring is ungated, permits duplicates, and defaults `nutrient_overrides` to `{}` — `routes/menus.py:346-367`
- §3.4 — insert — ambiguity — a ballot bumps the cycle's version only when a derived figure actually changes — `routes/menus.py:314-319`
- §3.5 — insert — ambiguity — `allow_waitlist` is echoed on the reservation — `routes/reservations.py:99-121`
- §3.5 — revise — mismatch — reservation-create gates narrated in §2.6 tier order (suspended → verified order → participation → care level → spacing → capacity) — `routes/reservations.py:99-150`
- §3.5 — revise — mismatch — seat gates narrated in actual order (state → venue → tray card → verified order → deferred `ERR_NO_PUBLISHED_MENU_CYCLE`) — `routes/reservations.py:166-228`
- §3.5 — insert — ambiguity — the seating cascade's RESIDENT ticket takes `issued_by_user_id` from the caller and bypasses every issuance gate — `routes/reservations.py:166-228`
- §3.5 — insert — ambiguity — waitlist promotion picks a single `created_at` winner, uses the meal-period roll-up, and requires a COMPLIANT posture — `services/derive.py:140-161`
- §3.6 — revise — mismatch — issuance gates renarrated in §2.6 tier order (reservation link before posture/verification); a RESIDENT ticket with no `resident_id` reports `ERR_DIET_ORDER_NOT_VERIFIED` — `routes/tickets.py:104-139`
- §3.6 — insert — ambiguity — sponsor `dining_status` is not an issuance gate — `routes/tickets.py:130-139`
- §3.6 — insert — ambiguity — serve is gated on posture only, never on venue `status` — `routes/tickets.py:170-175`
- §3.7 — insert — ambiguity — `temperature_f` is unbounded and at most 1 dp; an empty-string corrective code counts as present — `routes/venues.py:107-117`
- §3.8 — insert — ambiguity — `intake_pct` is an integer 0–100 and `weight_kg` at most 1 dp — `routes/residents.py:199-200`
- §3.8 — insert — ambiguity — cascade hops 3 and 4 no-op unless the ACTIVE order is `APPROVED` — `routes/residents.py:265-282`
- §3.8 — revise — mismatch — `DIET_ORDER_REREVIEW` forces `review_status` to `REREVIEW_REQUIRED` from any prior value — `routes/reviews.py:92-95`
- §3.8 — insert — ambiguity — the review's `note` is stored but absent from the response body — `serialize.py:232-243`
- §3.9 — insert — ambiguity — a `variance_note` counts as supplied only with a non-whitespace character, and an omitted note leaves the stored value untouched — `routes/reconciliations.py:88-96`
- §4 — revise — mismatch — menu-item endpoint description corrected: the slot add is ungated by cycle status, not restricted to a draft cycle — `routes/menus.py:118-160`

Deliberately not pinned, to honour minimality: the catch-all 404/405 handler's use of `ERR_INVALID_REQUEST` for undeclared paths, JSON float rendering of 2-dp decimals, and duplicate entries being tolerated inside enum arrays.

**Orchestrator verification:** `wc -l -c` confirms 466 lines / 103,798 chars (source 466 / 96,466 → +7,332 chars, 0 line delta); tail ends on the complete final §5 table row `| ERR_VARIANCE_UNRESOLVED | 409 |`; 5 top-level sections and all 41 `ERR_*` ids still present. Not truncated.

---

# Pipeline complete — 2026-09-02T18:58:30.000Z

All 9 steps done (Step 8 skipped by its stated skip condition). Final artifacts in place: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 modules), `test_suite/` (conftest + 15 modules, 99 tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (57 endpoints, in-memory only) and `workspace/implementation/results.{1..8}.json` from the passing 8-round sweep (99/99 in every round).
