# Worklog — task_0447_nightclub_bar

## Step 1: Create task directory — 2026-06-21T00:00:00.000Z

Created `tasks/task_0447_nightclub_bar/workspace`. Index 0447 derived by scanning existing `tasks/task_NNNN_*` directories and incrementing the max. Scenario: Nightclub & Bar Service (cover charge & guest list, table/bottle-service reservation & minimum, tab/bar POS & pre-authorization, occupancy/fire-code count, age/ID verification & refusal log, comp & promoter tracking, security incident, last-call & responsible-service).

## Step 2: Generate scaffold — 2026-06-21T00:00:00.000Z

All three files are written and the lint verdict is clean. Here is the summary of what I generated.

## Summary

Generated three scaffold artifacts for **task_0447_nightclub_bar** from the verbatim scenario, with no reference to any sibling task. `scaffold_lint.py` returns **VERDICT: clean lint** (220 calls scanned across §1.8/§1.9, all conform to §1.5; all 14 FKs reverse-reachable).

**Design profile:** primary archetype *Quota/allocation* (fire-code occupancy) + secondary *Pricing engine*; **flat topology** under `api_prefix /nightclub` (every entity a peer collection, FKs in bodies, resolved via filtered-list GETs); posture-driven state shape; peer-roles RBAC; immediate consistency. Advanced band.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **9 entities:** Venue (root with derived `posture` OPEN/AT_CAPACITY/LAST_CALL/CLOSED, `occupancy_count`), Promoter, GuestListEntry, Reservation, Tab, TabItem (`common_fields:false`), Entry, IdCheck, SecurityIncident.
- **4 state machines:** Venue (posture-driven, CLOSED terminal w/ cascade), Reservation (branching fork BOOKED→{SEATED,NO_SHOW,CANCELLED}→SETTLED), Tab (branching-with-revert OPEN↔RUNNING→SETTLED/VOIDED), Entry (INSIDE→EXITED/EJECTED). **2 concurrency rules** (OCC on `Venue.version` for admit & reserve, both 412).
- **5 calculations:** `cover_charge_amount` (surge→discount→comp, modes-a), `tab_final_total` (sum-then-round gratuity, mode-b), `reservation_minimum_shortfall` (pinned circular tab↔shortfall order, mode-c), `patron_age_years`, `id_check_outcome` (expiry-overrides-age).
- **17 validations** (priority-ordered auth→existence→state→safety→temporal→constraint→fiscal), **18 errors**, **5 roles** (PlatformAdmin, FloorManager, DoorHost, Bartender, SecurityOfficer; all `opaque`), **38 endpoints** (incl. test-driving `/_clock/set_current_utc` default `2026-01-01T00:00:00Z` and `/_inject/occupancy`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all **9 rule_ids**, **19 instances** total (each rule ≥2; combinatorial_formula has 3 covering modes a/b/c). All formula-derived asserts are pre-computed literals (e.g. cover 800/1500/2000/3000, tab 5773, shortfall 42800→final 50000, age 21=PASS/20=REFUSED).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **9 sections** (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model), **37 instances** (33 active + 4 `excluded_because:` stubs that correctly cite §1.8 instances by name).

**Cross-file checks:** no name collisions; no unbound `${var}` placeholders; no forbidden concurrency vocabulary; design keys do not leak into SCAFFOLD.yaml; fixed one enum dead-end (removed unproducible `GuestListEntry.EXPIRED`).

## Step 3: Copy shared files — 2026-06-21T00:00:00.000Z

Copied `INSTRUCTION.md` (53 lines) → `tasks/task_0447_nightclub_bar/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-21T00:00:00.000Z

Generated `workspace/PRD.md` from the nightclub-bar scaffold.

**Document shape**
- **269 lines**, 5 top-level sections (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue).
- **§2:** 9 domain-derived subsections (RBAC, fixed Response Structure, Pagination, Common Resource Properties + logical clock, Monetary Precision, Venue Posture gate, Hierarchical Consistency/close cascade, Nested Resolution + FK integrity, Optimistic Concurrency).
- **§3:** 10 scattering-zone subsections organized by domain lifecycle (venue standup, promoters/guest-list/comp budget, door ID verification, admission/cover, exit/ejection, reservations, bar tab settlement, close cascade, security incidents, validation ordering).
- **§4:** 38-row endpoint table, exactly 4 columns. §5: 18-row error table, 2 columns.

**Hard Contract results (all PASS)**
- Contract 1 (Field-Name Coverage): 61/61 required field names present; 0 missing.
- Contract 2 (Rule Coverage): all 18 error IDs and all enum/state values present; 34 behavioral spot-checks pass.
- Contract 3 (§3 Path Purity): 368 §3 backtick tokens scanned; 0 path/method leaks.

**Confirmation:** SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were NOT read.

## Step 5: Generate unit tests — 2026-06-21T00:00:00.000Z

Generated complete test infrastructure for `task_0447_nightclub_bar` under the design-index-only contract.

**Test helpers written (9 files):** `__init__.py` (barrel export), `types.py` (9 entity TypedDicts + 9 enums; TabItem correctly omits `updated_at`/`version` as append-only), `api_client.py` (one method per endpoint incl. `_clock`/`_inject`), `api_errors.py` (18 error IDs + HTTP map, registered), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (5 opaque roles), `fixtures.py` (composite setup: venue/admit/occupancy-inject/reservation/tab/last-call/close chains).

**Test files written (7 files, 69 test functions):** `conftest.py`, `test_01_venue_crud_and_rbac.py` (9), `test_02_id_checks_and_cover.py` (6), `test_03_admission_occupancy.py` (13), `test_04_reservations.py` (14), `test_05_tabs_and_settlement.py` (17), `test_06_close_responsible_service_promoters.py` (10).

**Coverage (audited programmatically):**
- **Queue A (Difficulty):** 18 of 19 instances translated, each with ≥2 tests. **1 instance SKIPPED** — `combinatorial_formula/cover_charge_surge_then_discount_then_comp_mode_a`: PRD §3.4 formula uniquely derives `cover_paid = 1300` (surged 3000 × (1−0.5) = 1500, minus comp 200), but the instance asserts `800`. Literal not PRD-derivable → unique-derivability filter fail, left as gap (not weakened/xfail'd). Rule still has ≥2 tests via its other instance.
- **Queue B (Corner):** 33 of 33 non-stub instances translated (≥1 test each). All 4 `excluded_because` stubs correctly NOT translated; every `difficulty_instance` cross-reference resolves.

**Quality gates passed:** every test docstring ends with exactly one `Design:` tag; all 96 quoted PRD citation fragments verified verbatim against PRD.md; no `skip`/`xfail`/`skipif`; no scaffold leakage; all modules import cleanly.

## Step 6: Generate implementation — 2026-06-21T00:00:00.000Z

Built a complete Python + Flask implementation for the Nightclub & Bar Service API at `workspace/implementation/`.

**Files written (10):** `start.sh` (foreground launcher, executable), `requirements.txt` (`flask==3.0.3`), `app.py` (all 38 routes, error handlers, validation-priority ordering), `domain.py` (entity serialization, computed fields, posture recomputation, calculations, state transitions, cascades), `clock.py`, `db.py` (in-memory store), `errors.py` (18 error-id constants), `response.py`, `middleware.py` (auth + RBAC), `validators.py`.

**Storage:** In-memory only (plain dicts in `db.py`). Store starts empty on every boot — no seeding/preload/hardcoded entities. Verified fresh boot returns 0 venues.

**start.sh / PORT / 0.0.0.0 / foreground:** `cd "$(dirname "$0")"`, guards pip install behind `if ! python3 -c "import flask"`, then `exec python3 app.py`. `app.py` reads `int(os.environ.get("PORT", "10000"))`, calls `app.run(host="0.0.0.0", port=port, threaded=True)`. `exec` replaces shell so signals propagate for per-test-server kill/restart.

**Endpoints implemented: 38** (36 business + `/_clock/set_current_utc` and `/_inject/occupancy`).

**One bug found & fixed during impl self-test:** reservation-settle cascade originally re-applied gratuity to the minimum top-up line, producing a total above `spend_minimum_cents`; fixed by pinning final total to `grand_step1 + shortfall` so it lands exactly on `spend_minimum_cents` per PRD §3.7.

## Step 7: Run tests and iterate — 2026-06-21T00:00:00.000Z

All 8 parallel rounds are clean: `passed == total == 69`, `failed == 0`, with no skipped or errored tests.

**Iterations run:** 1 (the initial 8-round parallel stability sweep passed clean on the first attempt — all 8 rounds reported `passed == total == 69`, `failed == 0`, `skipped == 0`).

**Tests deleted:** None. No test failed in any of the 8 rounds.

**Fixes applied to `test_helpers/`:** None required.

**Fixes applied to `implementation/`:** None required.

**Notes on diagnosis read-through (no failures surfaced):**
- Implementation is a clean Flask app with strict in-memory storage (dicts only, empty on boot — `db.py`), logical clock defaulting to `2026-01-01T00:00:00Z` (`clock.py`), full validation priority order from PRD §3.10 wired into routes (`app.py`).
- Test suite (69 tests across 6 files) traces each assertion to verbatim PRD prose; the one PRD-non-derivable design instance (`cover_charge_surge_then_discount_then_comp_mode_a`, design asserted 800 but PRD §3.4 uniquely derives 1300) was already correctly omitted in `test_02_id_checks_and_cover.py`.
- Timing-sensitive areas (OCC version-threading on admit/book, capacity boundary, posture recomputation on clock-set, last-call/close cascades, per-test-server port allocation) all held across 8 concurrent rounds with no flakiness.

## Step 8: Finalize PRD — SKIPPED — 2026-06-21T00:00:00.000Z

Skipped per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). `PRD.md` already determined every behavior the implementation exhibits at every Step 7 site. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-06-21T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD.md` (Step 8 skipped, so started from PRD.md), pinning every place the prose admitted multiple readings to the behavior `implementation/` actually adopts.

**File metrics:** `PRD.md` 269 lines / 45,883 chars → `PRD_COMPLETED.md` 269 lines / 47,672 chars — char delta **+1,789**. Edits touch 9 lines; all in-paragraph inserts/revisions. No new sections, no reordering.

**Counts:** 8 ambiguity-pins, 1 mismatch-revision.

**Per-change**
- §2.3 (Pagination) — insert — ambiguity — out-of-range `limit`/`offset` silently clamped (limit→[1,100], offset→≥0); non-integer → `ERR_INVALID_REQUEST` — validators.py:105-131.
- §2.3 (Pagination) — insert — ambiguity — `created_at` ties broken by creation/insertion order (stable ascending) — app.py:48, db.py:13-14.
- §3.1 (Standing Up a Venue) — revise — mismatch — posture `OPEN` at creation but derived once against clock, so a venue whose closing/last-call window already encloses present clock is created `LAST_CALL` — app.py:89, domain.py:82-96.
- §3.2 (Guest Lists) — insert — ambiguity — only a `CONFIRMED` entry may be cancelled; cancelling `REDEEMED`/`CANCELLED` → `ERR_INVALID_STATE` — app.py:258-259.
- §3.6 (Booking a Table) — insert — ambiguity — `minimum_shortfall_cents` is `null` until reservation settled — app.py:507, domain.py:187,414.
- §3.6 (Booking a Table) — insert — ambiguity — seating during `LAST_CALL` → `ERR_INVALID_STATE` (closed venue caught earlier as `ERR_VENUE_CLOSED`) — app.py:556-558.
- §3.7 (Bar Tab) — insert — ambiguity — opening a tab during `LAST_CALL` → `ERR_INVALID_STATE` — app.py:651-652.
- §3.7 (Bar Tab) — insert — ambiguity — voiding a line requires `OPEN`/`RUNNING` tab + un-voided line; else `ERR_INVALID_STATE` — app.py:755-758.
- §3.10 (test-driving note) — revise — ambiguity — clock-set returns empty `data`; occupancy-inject returns updated venue and, when `target_inside` < current, exits most-recently-created `INSIDE` entries down to target — app.py:894,911-951.

**Already-pinned (no change):** cover surge→discount→comp ordering + variants (§3.4); sum-then-round gratuity + minimum top-up ordering (§3.7); validation priority order, OCC version-bump rules, ID-check expiry-before-age gate, ejection/close cascades, §5 error/HTTP mapping all match implementation verbatim.

---

## Pipeline complete

All 9 steps done. Final state: 69/69 tests pass across 8 parallel stability rounds. Task artifacts complete under `tasks/task_0447_nightclub_bar/`.
