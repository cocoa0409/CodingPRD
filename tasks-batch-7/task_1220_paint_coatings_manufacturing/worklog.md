# Worklog — task_1220_paint_coatings_manufacturing

## Step 1: Create Task Directory — 2026-08-12T00:33:38.000Z

Pre-assigned output folder `tasks/task_1220_paint_coatings_manufacturing` with `workspace/` subdirectory already exists. Step 1 treated as done per pipeline instruction (no auto-index scan run).

## Step 2: Generate Scaffold — 2026-08-12T01:35:19.000Z

Scaffold generation complete for task 1220 (Paint & Coatings Manufacturing), written to `/home/ubuntu/github/CodingPRD/tasks/task_1220_paint_coatings_manufacturing/`. All three files verified on disk; `scaffold_lint.py` verdict:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
(73 endpoints, 14 entities, 20 §1.8 instances, 45 §1.9 instances, 1017 calls scanned)
```

**Counts**
- Entities: 14 (Customer, TintBase, Colorant, Formula, FormulaLine, VocRule, Mill, Batch, BatchAdjustment, ColorMatch, Container, SalesOrder, CreditClaim, DisposalRequest)
- State machines: 9 (Formula, VocRule, Mill, Batch, ColorMatch, Container, SalesOrder, CreditClaim, DisposalRequest)
- Calculations: 12
- Validation priority rows: 11
- Endpoints: 73 (includes `POST /_clock/set_current_utc` with the mandated 2026-05-01T00:00:00Z default, plus a daily ops sweep)
- Errors: 26 (all triggerable by at least one design instance)
- Roles: 6 (5 opaque + Dealer entity_backed:Customer; segregation-of-duties model)
- Difficulty instances: 20 — dual_variant 2, combinatorial 3 (modes a/b/c), non_linear_sm 2, transitive_cascade 2 (depths 3 and 2), priority_conflict 2 (state/safety, referential/temporal), boundary 3, cross_entity 2, temporal_overlap 2 (half-open VocRule windows vs closed+buffer Mill reservations), compensating_invariant 2 (credit-ledger cents, mill reserved-minutes)
- Corner instances: 45 across all nine claim-guide sections (no excluded stubs needed)

**Harder-than-expert levers pushed per the difficulty parameter**
- Cyclic Batch machine with a dispersion self-loop, a QC rework cycle, and a rework cap (3rd rejection condemns to DISPOSAL_PENDING) — plus a depth-3 cascade (successor formula activation → predecessor DEPRECATED → PLANNED batches ON_HOLD → orders BLOCKED) with a resume path that unwinds it.
- Every numeric assertion in both design files was precomputed as a literal via Python (VOC 154.57 g/L, order totals 574220/47000/212500, batch cost 4860 vs 30040, fill recon 13.83 vs 13.82 rounding-order divergence, credit bands at exactly 360/359 remaining days, disposal net 57050, etc.).
- Logical-clock determinism for shelf-life expiry, retain-sample purge, 30-day claim window (second-precision boundary), and date-keyed rush quota reset.
- One true OCC concurrency rule (`formula-supersede-stale-version`) that passes the serial-observability filter: supersede leaves the predecessor ACTIVE until a successor activates, so a stale `expected_formula_version` is the only discriminator.

Files: `SCAFFOLD.yaml` (95 KB, §1.0–§1.7 only), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (99 KB, single `scaffold_difficulty_design` key), `SCAFFOLD_CORNER_DESIGN.yaml` (160 KB, single `scaffold_corner_design` key).

## Step 3: Copy Shared Files — 2026-08-12T01:35:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1220_paint_coatings_manufacturing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T01:52:00.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_1220_paint_coatings_manufacturing/workspace/PRD.md` (341 lines, 61 KB). The two forbidden index files were never opened or referenced.

## Section list
- **§1 Introduction** (3 paragraphs: business context, regulatory/financial pressures, document map)
- **§2 Global Specifications** — 2.1 RBAC (6 roles, per-role `identity` prose: Dealer entity-backed to `Customer`, five opaque roles), 2.2 API Response Structure (byte-identical to the fixed verbatim block — diff-verified), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties (UUID `id`, 3-fraction-digit timestamps, `version`; `FormulaLine`/`BatchAdjustment` explicitly carry only `id`+`created_at`), 2.5 Logical Clock & Calendar Arithmetic (default 2026-05-01T00:00:00Z, `to_iso8601`/`current_utc`, month/day/second precisions), 2.6 Units & Rounding, 2.7 OCC (`expected_formula_version` → `ERR_STALE_VERSION` 412, supersede-only), 2.8 Cascading Consistency, 2.9 Validation Order (all 11 priority gates in explicit order), 2.10 Mill Windows & Washdown Buffers
- **§3 Business Logic** — 9 subsections: product library (bases/colorants/formulas/supersede/activate/deprecate), VOC governance + ship-time resolution, orders/pricing/rush, batch planning + mills, milling/dispersion/adjustments + VOC recomputation, color QC/rework/retain, filling/weighing/reconciliation, shipping/returns/shelf-life/credit claims, disposal/destruction
- **§4 Endpoint Definitions** — 73 rows (4 columns only)
- **§5 Error Code Catalogue** — 26 rows (2 columns only)

## Hard-contract reports
- **Contract 1 (Field-Name Coverage): PASS** — 131 required identifiers (all entity fields, request-body/query/path params, plus clock/sweep outputs), 131 present in backticks, 0 missing. (Note: the first audit pass mis-reported because whole-file regex pairing breaks across code fences; the authoritative line-wise pass confirms full coverage.)
- **Contract 2 (Rule Coverage): PASS** — validations[] priority: 11/11 gates expressed in order (§2.9); concurrency_rules[]: 1/1 (write endpoint + `expected_formula_version` + `ERR_STALE_VERSION`/412, no race framing); state-machine transitions: 60/60 across all 9 machines with from/to states, preconditions paired to error ids, and side effects (incl. depth-3 formula→batch→order cascade, rework-cap condemnation, divergent rush approve/reject, per-source-state dispose cascades, triple pre_disposal_status restore); calculations[]: 12/12 in precise reconstructable prose (voc_actual_gpl, voc_compliance_resolution, order_pricing pinned order, fill_weigh_check, fill_reconciliation with pinned per-container rounding and the 13.83≠13.82 example, batch_cost both variants, freeze_credit_calc bands/penalties/variants, rush_capacity 3rd-passes-4th-fails, disposal_cost, lifecycle_dates, claim_window inclusive 30-day boundary, mill_reservation closed-interval/washdown rule); all 26 error ids appear in §1–§3 narrative; all 56 state/enum literal values present; sibling branches rendered symmetrically.
- **Contract 3 (§3 Path Purity): PASS** — 556 backticked tokens in §3; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos (the only path literal in the document is the `/coatings` mount in §1, which is permitted).

Every scaffold entity (14), state machine (9), calculation (12), validation (11), concurrency rule (1), error (26), endpoint (73), and role (6) is mapped to a PRD passage as itemized above.

## Step 5: Generate Unit Tests — 2026-08-12T02:24:52.000Z

Complete. Test infrastructure and suite for task_1220 are generated and verified.

## test_helpers/ (9 files)
All at `/home/ubuntu/github/CodingPRD/tasks/task_1220_paint_coatings_manufacturing/test_helpers/`:
- `types.py` — 13 status/field enums + 13 entity TypedDicts; FormulaLine/BatchAdjustment correctly modeled append-only (no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (52 methods incl. `/_clock/set_current_utc` and the daily sweep)
- `api_errors.py` — `ApiErrorId` (26 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + ledger/order/disposal invariant checkers
- `factories.py` — payload factories for all creatable resources (canonical TB1/TB2/TB3, C1/C2 values)
- `constants.py` — all calculation thresholds (tolerances, bands, fees, rates, retention months, washdown buffer, rush limit)
- `test_users.py` — opaque-role header constants + `make_dealer_headers(customer_id)` for the entity-backed Dealer
- `fixtures.py` — composite chains: canonical catalog builders, `drive_batch_to_qc_approved/filled`, `setup_shipped_container`, `setup_approved_claim`, disposal helpers
- `__init__.py` — barrel export

## test_suite/ (13 files, 85 tests, all collected by pytest)
`conftest.py` + `test_01_master_data` (8), `test_02_formula_lifecycle` (5), `test_03_voc_rules` (2), `test_04_mill_scheduling` (7), `test_05_batch_workflow` (11), `test_06_color_qc` (9), `test_07_orders_pricing` (11), `test_08_shipping_voc` (7), `test_09_containers_lifecycle` (5), `test_10_credit_claims` (11), `test_11_disposal` (4), `test_12_rbac` (5).

## Coverage
- **Queue A (§1.8 difficulty): 20/20 instances translated, each with ≥2 tests** (40 tests). Every docstring ends with `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (§1.9 corner): 44/45 non-stub instances translated** (45 tests), each tagged `Design: Corner/<section>/<instance.name>`. No `excluded_because` stubs exist in this index.
- **Skipped (1)**: `Corner/state_machines/tint_shot_during_milling_returns_invalid_state` — PRD §3.5 states adjustments are "phase-gated by kind" but never states which kinds belong to which phase, so the asserted outcomes (TINT_SHOT rejected in MILLING; THINNER accepted in MILLING) fail the two-reader unique-derivability test. Not weakened, not marked — the gap stays a gap.

## Verification performed
- `py_compile` clean on all 22 files; `pytest --collect-only` collects exactly 85 tests with zero errors
- Tag audit: all 85 tests carry exactly one Design tag; every tag resolves to a real instance; 20 difficulty instances all have ≥2 tags; 44 corner instances have ≥1
- Verbatim-citation pass: every quoted passage in every test docstring greps literally in `PRD.md` (85/85 pass)
- No `skip`/`skipif`/`xfail` markers anywhere; no scaffold references in comments

Notable translation choices (PRD-adjudicated): version-initial-value assertions were made relative (`version == captured + 1`) because the PRD specifies increment-on-mutation but not the initial value; timestamp equality assertions use logical-clock prefix comparison since the PRD pins the instant but the millisecond format only for `created_at`/`updated_at`; the retain-purge assertion reads `retain_purged_at` via GET rather than asserting membership in `purged_retain_sample_ids` (id vs sample-id ambiguity in PRD naming).

## Step 6: Generate Implementation — 2026-08-12T02:24:52.000Z

Done. The implementation is complete and verified.

## Summary

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_1220_paint_coatings_manufacturing/workspace/implementation/`

**Files (20):**
- `start.sh` (396 B) — guarded install (`pip install` only if `flask` import fails), `exec python3 app.py` in foreground
- `requirements.txt` (11 B) — `flask>=3.0`
- `app.py` (1,362 B) — Flask assembly, envelope-wrapped error handlers (ApiError/404/405/500), `0.0.0.0:$PORT`
- `coatings/store.py` (1,122 B) — in-memory dicts keyed by id, logical clock defaulting to `2026-05-01T00:00:00Z`; **no seeding anywhere**
- `coatings/errors.py` (674 B) — ApiError carrying the scaffold error IDs
- `coatings/util.py` (7,817 B) — Decimal half-up helpers, ISO-8601 parse/format (3 fractional digits), envelope (`meta`/`response_type`/`data`, `limit`/`offset`/`total_count`/`has_more`), auth (gates 1–2), field validators
- `coatings/domain.py` (16,761 B) — all constants, calculations (voc_actual_gpl, order pricing, fill weigh/reconciliation, batch cost variants, freeze credit bands, rush capacity, disposal cost, mill reservation), serializers, formula-deprecation cascade
- `coatings/views_*.py` (12 modules, ~63 KB total) — customers, catalog (bases/colorants), formulas (+supersede OCC/activate/deprecate cascades), VOC rules (half-open window overlap), mills, batches (full pipeline), color matches (segregation, retain samples, rework loop), containers (reweigh/ship VOC gate/returns/freeze), orders (rush fork, capacity 3/day, volume fulfillment), credit claims (review/approve/settle/void ledger), disposal requests (manifest, quantity gate, cost), ops sweep + `/_clock/set_current_utc`

**Endpoints registered:** exactly **73** (method, path) pairs (74th route is Flask's auto static rule; excluded from the count).

**Boot verification:** `PORT=10099 bash start.sh` boots in ~1 s; `GET /coatings/voc-rules` returned HTTP 200 with correct envelope (`{"data":[], "meta":{...,"limit":10,"offset":0,"total_count":0,"has_more":false}, "response_type":"array"}`); process then killed cleanly. Fresh-reboot isolation confirmed: a second boot shows an empty store.

**Behavioral verification (3 suites, ~110 checks, all passing):** auth 401/403 masking; schema(400)→existence(404)→OCC(412)→state(409) gate ordering (including schema masking 404 on missing path ids); supersede version advance + stale rejection; activate cascade (predecessor→DEPRECATED, PLANNED batches→ON_HOLD, SCHEDULED orders→BLOCKED) with version bumps; dispersion self-loop; phase-gated adjustments; VOC recompute (verified 88.68 and 46.97 by hand); segregation of duties (color match, claim settle); rework cap → 3rd rejection condemns batch; fill tolerance/quarantine/reweigh; per-container-rounding reconciliation; order pricing (line-round-then-sum, rush fee keyed on pre-fee subtotal); rush daily cap 3; volume-based fulfillment incl. stock-only PLACED→FULFILLED; claim window at exactly +30d passes / +30d1s fails; freeze penalty claimed-vs-verified divergence; annual credit cap; settle/void ledger reversal; sweep (expiry-day obsolete, retain purged strictly after); disposal manifest gating, quantity gate, hazmat pricing; mill window conflicts with 30-min washdown buffer and boundary adjacency.

One deliberate spec-fidelity call: disposal `hazmat_class` is computed from referenced **containers'** batches only (per the literal scaffold/PRD formula), so batch-only requests classify NON_HAZARDOUS.

## Pre-Step-7 route parity check — 2026-08-12T02:26:00.000Z

Orchestrator-verified: SCAFFOLD.yaml declares 73 (method, path) endpoint pairs; implementation registers exactly 73 routes; 1:1 match after normalizing Flask `<param>` vs scaffold `{param}` placeholder syntax. No missing or extra routes.

## Step 7: Test-diagnosis iteration — 2026-08-12T03:05:00Z

First 8-round parallel sweep (`--isolation per-test-server`): 77/85 passed in every round; the same 8 tests failed in all 8 rounds (zero flakiness). Union-of-failures diagnosis per the PRD-first protocol:

1. `test_04::test_mill_reservation_released_only_at_terminal` — IMPLEMENTATION BUG. `ser_mill` computed `reserved_minutes` as the sum over `RESERVED_STATES` which omitted `DISPOSAL_PENDING`, releasing the reservation at condemnation instead of at DISPOSED. PRD §2.10 ("The reservation is released ... when the batch is cancelled or reaches `DISPOSED`") and §3.7 ("its mill reservation is finally released") pin release-at-DISPOSED; the implementation's own `_check_window_conflict` already treated DISPOSAL_PENDING as reserving (`NO_RESERVATION_STATES = CLOSED/DISPOSED/CANCELLED`). Fix: added `DISPOSAL_PENDING` to `RESERVED_STATES` in `coatings/domain.py`. (Scaffold §1.1 field def confirms: the sum list includes DISPOSAL_PENDING; released at CANCELLED or DISPOSED.)
2. `test_05::test_batch_resume_requires_active_new_formula` — ERROR PRECEDENCE SILENCE. Start-mill on an ON_HOLD batch (formula deprecated → cascade held the batch): §3.5 names `ERR_FORMULA_NOT_ACTIVE` for "a formula deprecated since planning blocks the start", but the deprecation cascade makes PLANNED-with-deprecated-formula unreachable, so §2.9's gate order (state gate 6 before referential gate 8) admits `ERR_INVALID_STATE` too. Relaxed the one assertion to `validate_error_is_one_of([ERR_FORMULA_NOT_ACTIVE, ERR_INVALID_STATE])` (permitted relaxation; both error ids PRD-named).
3. `test_06::test_rework_cap_condemns_batch_on_third_rejection` — TEST BUG. The loop only invoked the rework action after the first rejection, then issued a dispersion check against a REWORK batch (dispersion checks run in MILLING, §3.5; the rework action moves REWORK→MILLING, §3.6). Fixed the loop to run the rework action in every cycle ("two full reject/rework cycles").
4. `test_08::test_ship_requires_resolvable_voc_rule`, `test_08::test_ship_succeeds_once_covering_rule_activated`, `test_08::test_voc_rule_resolution_excludes_draft_rules` — FIXTURE BUG. `create_tb3` used density 4.4 kg/gal: a 2-gal batch's drawdown (8.8 kg) cannot be reconciled with two nominal GALLON cans (weigh gate requires ≥ 4531 g/can ⇒ ≥ 9.062 kg filled ⇒ 4.5% deviation > 0.5%); the weigh-pass and reconcile-pass intervals are disjoint, so no PRD-consistent request sequence could drive a TB3 batch to FILLED. Density is a fixture-chosen constant (PRD pins only that it exists and feeds reconciliation). Fix: TB3 density 4.6 in `test_helpers/fixtures.py` (and the canonical table in `factories.py` docstring).
5. `test_10::test_freeze_credit_provisional_vs_final_variants`, `test_10::test_freeze_credit_band_boundary_360_vs_359` — FIXTURE BUG. The tests calibrate `remaining_days_at_claim` (721 / 360 / 359) against expiry 2028-06-10, but `setup_shipped_container` filled containers at the default clock 2026-05-01 (expiry 2028-05-01). Fix: the fixture now sets the logical clock to 2026-06-10T10:00:00Z before filling (mirroring `_setup_voc_matrix`/test_09's convention); manufacture-at-10:00 vs claim-at-08:00 makes the asserted values hold under both whole-day readings (timestamp-floor and calendar-date).

Smoke-verified all five repaired scenarios against a live boot before rerunning the sweep (reservation hold/release, rework-cap condemnation, TB3 reconciliation, 721-day provisional/final, 360-vs-359 bands, ON_HOLD start-mill error).

### Step 7 final summary — 2026-08-12T02:46:11.000Z (subagent returned; orchestrator-verified all 8 results files on disk: 85/85 passed in every round)

**Iterations run:** 2 sweeps of the 8-round parallel protocol (round 1: 77/85 with the same 8 failures in all 8 rounds — zero flakiness; round 2 after fixes: **85/85 in all 8 rounds**).

**Tests deleted:** none. Every failure traced to either an implementation bug, a test/fixture bug, or a permitted precedence relaxation — no test asserted a rule the PRD is silent on.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `create_tb3`: density 4.4 → 4.6 kg/gal. With 4.4, the fill weigh gate (≥4531 g per GALLON can) and the 0.5% reconciliation band (≤4422 g per can at 2 gal drawdown) admit no common fill weight, so no PRD-consistent request sequence could drive a PRIMER batch to FILLED (root cause of the 3 `test_08` primer-shipping setup failures).
- `test_helpers/fixtures.py` — `setup_shipped_container`: now sets the logical clock to 2026-06-10T10:00:00Z before filling, so containers are manufactured 2026-06-10 and expire 2028-06-10 — the date the credit-band tests calibrate `remaining_days_at_claim` (721 / 360 / 359) against. The 10:00-vs-08:00 time-of-day offset makes the asserted values hold under both whole-day readings (timestamp-floor and calendar-date).
- `test_helpers/factories.py` — canonical-table docstring updated for TB3 density (cosmetic consistency).

**Fixes applied to `test_suite/`:**
- `test_06_color_qc.py::test_rework_cap_condemns_batch_on_third_rejection` — the loop invoked the rework action only after the first rejection, then issued a dispersion check against a REWORK batch; PRD §3.5/§3.6 define dispersion checks as a MILLING activity reached from REWORK only via the rework action. The loop now reworks in every cycle, matching its own "two full reject/rework cycles" intent.
- `test_05_batch_workflow.py::test_batch_resume_requires_active_new_formula` — ERROR PRECEDENCE SILENCE relaxation: start-mill on an ON_HOLD batch (held by the deprecation cascade) now asserts `validate_error_is_one_of([ERR_FORMULA_NOT_ACTIVE, ERR_INVALID_STATE])`. §3.5 names `ERR_FORMULA_NOT_ACTIVE` for "a formula deprecated since planning blocks the start", but the cascade makes PLANNED-with-deprecated-formula unreachable, so §2.9's gate order (state gate 6 before referential gate 8) equally admits `ERR_INVALID_STATE`.

**Fixes applied to `implementation/`:**
- `workspace/implementation/coatings/domain.py` — added `DISPOSAL_PENDING` to `RESERVED_STATES` (used by `mill_reserved_minutes`). PRD §2.10 ("The reservation is released ... when the batch is cancelled or reaches `DISPOSED`") and §3.7 ("its mill reservation is **finally** released" at the DISPOSED transition) require a condemned batch to hold its reservation while `DISPOSAL_PENDING`. This also restores internal consistency with `_check_window_conflict`, whose `NO_RESERVATION_STATES = (CLOSED, DISPOSED, CANCELLED)` already treated DISPOSAL_PENDING as window-reserving.

## Step 8: Finalize PRD — 2026-08-12T02:51:11.000Z

Done. `workspace/PRD_FINALIZED.md` written.

**Line counts:** PRD.md 340 lines, PRD_FINALIZED.md 340 lines — 0% delta (2 lines revised inline, no insertions/deletions of lines).

### Changes (2 edits, both tracing to `<step_7_diff>`)

- **§2.10** — revise — added `DISPOSAL_PENDING` to the `reserved_minutes` state enumeration and noted a condemned batch's window still blocks new conflicting reservations — `workspace/implementation/coatings/domain.py:64-67` (`RESERVED_STATES` includes `DISPOSAL_PENDING`, the Step 7 impl fix) and `workspace/implementation/coatings/views_batches.py:57` (`NO_RESERVATION_STATES = (CLOSED, DISPOSED, CANCELLED)`).
- **§3.5** — revise — pinned start-mill error precedence: batch-state gate fires first, so a batch in any non-`PLANNED` state (including the cascade-produced `ON_HOLD`-with-deprecated-formula case) yields `ERR_INVALID_STATE` before the formula/mill/order conditions — `workspace/implementation/coatings/views_batches.py:169-176` (state check at :169 precedes formula check at :174).

### Step-7 items producing no PRD edit

- `create_tb3` density 4.4→4.6: pure fixture constant; PRD pins only that `density_kg_per_gal` exists and feeds reconciliation (§3.1, §3.7) — no silence.
- `setup_shipped_container` clock pin: fixture calibration so expiry lands 2028-06-10; PRD already pins expiry = manufacture timestamp + `shelf_life_months` calendar months (§3.7, §2.5) and `remaining_days_at_claim` as whole days (§3.8). Impl (`views_claims.py:53`) matches; tests don't distinguish floor-elapsed vs date-diff.
- `test_06` rework-loop fix: pure test bug; PRD already states dispersion checks run in `MILLING` and rework moves `REWORK`→`MILLING` (§3.5, §3.6).

### Per-edit pre-edit search log

**Edit 1 (§2.10 reserved_minutes enumeration):**
- (a) Subject: which batch states hold a mill reservation / count toward `reserved_minutes` and window conflicts.
- (b) Enumerated: `domain.py:63-67` (`RESERVED_STATES` + comment), `domain.py:114-119` (`mill_reserved_minutes`), `domain.py:349` (mill serializer), `views_batches.py:57,66-75` (`_check_window_conflict` — `DISPOSAL_PENDING` windows do conflict), `views_batches.py:139` (reservation placed), `views_batches.py:401` (FILLED leaves the set), `views_batches.py:435-447` (cancel releases), `views_batches.py:450-466` (dispose → `DISPOSAL_PENDING`), `views_disposals.py:155` (complete → `DISPOSED`), `views_mills.py:46-51` (`ERR_MILL_BUSY` uses the separate `MILL_BUSY_STATES`, untouched), `views_mills.py:67-73` (mill batches listing is status-unfiltered).
- (c) Wording scoped to the `reserved_minutes`/conflict subject only, explicitly leaving §3.4's maintenance enumeration (which correctly excludes `DISPOSAL_PENDING`) untouched; release sentence kept verbatim since it already matches ("cancelled or reaches `DISPOSED`").

**Edit 2 (§3.5 start-mill precedence):**
- (a) Subject: validation order on `start-mill` when multiple start conditions fail.
- (b) Enumerated: `views_batches.py:163-185` (start_mill: `PLANNED` state → order `SCHEDULED` → formula `ACTIVE` → mill `ACTIVE`); parallel formula-active checks at `views_batches.py:101-103` (batch create), `:306-309` (resume — also state-before-formula), order placement and §2.9 gate order (gate 6 before gate 8); test site `test_suite/test_05_batch_workflow.py:233-244`.
- (c) Sentence claims only that the batch-state gate fires first (unambiguous in impl); it does not reorder the remaining three conditions (impl's order-state-before-formula already matches §2.9's gate 6-before-8) and invokes the existing §2.9 gate order rather than introducing a new rule.

## Step 9: Complete PRD — 2026-08-12T02:58:57.000Z

**File stats**
- Source `PRD_FINALIZED.md`: 340 lines, 61,501 chars → `PRD_COMPLETED.md`: 340 lines, 64,894 chars (+3,393 chars; all edits are inline insertions/revisions, no new sections).

**Counts**: 20 changes total — 19 ambiguity-pins, 1 mismatch-revision (order-line `size_code`).

**Changes (one per bullet: section — insert/revise — ambiguity/mismatch — what — impl ref)**

- §2.3 — insert — ambiguity — `limit`/`offset` validation failures are `ERR_INVALID_REQUEST` (non-integer, out-of-range, negative) — `coatings/util.py:94-97,109-116`
- §2.3 — insert — ambiguity — list sort ties broken by server creation sequence — `coatings/util.py:91`
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — `coatings/util.py:240-245`
- §2.5 — revise — ambiguity — clock set accepts any valid instant, no monotonicity check (not strictly "advances") — `coatings/views_ops.py:34-40`
- §2.9 gate 3 — revise — ambiguity — disposal request must reference ≥1 container or batch; `container_ids` present but may be empty when `batch_ids` given — `coatings/views_disposals.py:33-42`
- §2.9 gate 4 — insert — ambiguity — ownership-vs-existence on reads: customer read checks ownership first (403 on foreign id, existing or not); order/claim reads check existence first (404 before 403) — `coatings/views_customers.py:34-41`, `coatings/views_orders.py:115-122`, `coatings/views_claims.py:75-82`
- §2.10 — insert — ambiguity — window-conflict check considers every batch except `CLOSED`/`DISPOSED`/`CANCELLED`, so a `FILLED` batch's window still blocks (while its minutes leave `reserved_minutes`) — `coatings/views_batches.py:57,66-75`, `coatings/domain.py:64-67`
- §3.1 — revise — ambiguity — supersede successor inherits `tint_base_id` and `is_custom` from predecessor; `min_batch_gallons` recomputed from inherited `is_custom` — `coatings/views_formulas.py:154-166`
- §3.1 — insert — ambiguity — tint-base numeric fields floored at 0, `density_kg_per_gal` strictly > 0 — `coatings/views_catalog.py:28-38`
- §3.1 — insert — ambiguity — colorant `voc_g_per_unit`/`cost_per_shot_cents` ≥ 0 — `coatings/views_catalog.py:73-74`
- §3.1 — insert — ambiguity — formula `target_delta_e` non-negative; `lines` may be empty at creation; `sequence` is an integer — `coatings/views_formulas.py:32-44,73-74`
- §3.2 — revise — ambiguity — `effective_to` vs `effective_from` compared at calendar-day granularity (same-day later time still fails), at both creation and activation — `coatings/views_voc_rules.py:52-53,101-102`
- §3.2 — insert — ambiguity — `max_voc_gpl` ≥ 0 — `coatings/views_voc_rules.py:45`
- §3.3 — revise — **mismatch** — order-line `size_code` is optional/nullable (PRD implied required); `gallons` strictly positive — `coatings/views_orders.py:61-67`
- §3.3 — insert — ambiguity — fulfillment bubble-up fires only from `PLACED`/`IN_PRODUCTION`; never from `SCHEDULED`/`BLOCKED` — `coatings/views_containers.py:128-131`
- §3.4 — revise — ambiguity — mill `capacity_gallons` integer ≥ 1; enter-maintenance requires `ACTIVE`, return-to-service requires `MAINTENANCE` (else `ERR_INVALID_STATE`); mill-batch listing returns all batches ever planned on the mill, any status — `coatings/views_mills.py:19,44-45,60-61,67-73`
- §3.4 — insert — ambiguity — `planned_gallons` strictly positive; supplied `order_id` must exist (`ERR_NOT_FOUND`) — `coatings/views_batches.py:84,99-100`
- §3.5 — insert — ambiguity — start-mill condition order after batch-state: order-`SCHEDULED` (gate 6) → formula-active (gate 8) → mill-active (gate 10) — `coatings/views_batches.py:169-179`
- §3.5 — insert — ambiguity — `grind_reading` non-negative; passing reading does not increment `dispersion_cycles` — `coatings/views_batches.py:192,199-204`
- §3.5 — revise — ambiguity — adjustment phase table pinned: `THINNER`/`THICKENER`/`EXEMPT_SOLVENT` only in `MILLING`; `TINT_SHOT` only in `TINTING` — `coatings/views_batches.py:50-55,228-229`
- §3.5 — insert — ambiguity — submit-qc `actual_gallons` strictly positive — `coatings/views_batches.py:262`
- §3.6 — revise — ambiguity — `measured_delta_e` non-negative; verdict precondition order pinned (record `PENDING` → batch `QC_PENDING` → current cycle → delta-e → SoD); rejection has no delta-e check — `coatings/views_color_matches.py:21,65-88,101-106`
- §3.7 — revise — ambiguity — `actual_fill_g` integer grams (non-integer → `ERR_INVALID_REQUEST`); fills accepted in `QC_APPROVED` or `FILLING`; reweigh requires integer `actual_fill_g` even with `mark_rejected`, and reject does not apply the reading; zero/negative drawdown passes only when both filled mass and drawdown are exactly zero; `waste_gallons` ≥ 0 — `coatings/views_batches.py:326-338,386-391`, `coatings/views_containers.py:46-67`
- §3.8 — revise — ambiguity — claim approval allowed only from `UNDER_REVIEW`; `claimed_exposure_count` integer ≥ 0 — `coatings/views_claims.py:32-34,122-123`
- §3.8 — insert — ambiguity — customer `annual_credit_cap_cents` integer ≥ 0 — `coatings/views_customers.py:20`

All other implementation behaviors checked (envelope shape, error catalog statuses, OCC on supersede, deprecation cascade, VOC resolution incl. exemption and strictest-limit, pricing/rush fee order and tier key, rush daily cap, mill washdown/boundary rules, reserved-minutes state set, weigh-gate tolerance, fill reconciliation rounding order, VOC and cost formulas, retain-sample retention months, sweep semantics, claim banding/penalty/cap/settle/void ledger, disposal hazmat class/expected kg/manifest uniqueness/quantity gate/pricing/recovery cap/cancel restore) were already uniquely pinned by the PRD and required no change.

Output file: `workspace/PRD_COMPLETED.md`
