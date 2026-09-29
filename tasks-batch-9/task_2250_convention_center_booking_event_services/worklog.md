# Worklog — task_2250_convention_center_booking_event_services

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2250_convention_center_booking_event_services/` and `tasks/task_2250_convention_center_booking_event_services/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T00:20:00.000Z

All three artifacts are written and the lint is clean.

### Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2250_convention_center_booking_event_services/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2250_convention_center_booking_event_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2250_convention_center_booking_event_services/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    80
  §1.1 entities declared:     15
  §1.8 instances scanned:     26
  §1.9 instances scanned:     78
  Calls scanned (§1.8+§1.9):  1128

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

One fix round was needed: the first run reported 2 × `(f) FK_REVERSE_UNREACHABLE` for `SpaceUsageRecord.booking_id` and `SettlementLineItem.settlement_id` — both are `common_fields: false` append-only child rows with no GET-by-id, so the linter could not derive a collection segment for them. Resolved by adding two sub-resource reads (`GET /convention-center/bookings/{id}/usage-records` and `GET /convention-center/settlements/{id}/line-items`), taking the endpoint count from 78 to 80.

### Files

- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

Each design file carries exactly one top-level key; `SCAFFOLD.yaml` contains neither design key (top-level keys: `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`).

### Counts

| Section | Count |
|---|---|
| §1.1 entities | 15 |
| §1.2 state machines | 9 (2 of them are the two independent dimensions of `ServiceOrder`: `approval_status` and `billing_status`) |
| §1.2.1 concurrency rules | 2 (OCC on `EventBooking`, `LicenseAgreement`) |
| §1.3 calculations | 11 |
| §1.4 validations | 49 (priority 10 → 98) |
| §1.5 endpoints | 80 |
| §1.6 error catalog | 67 |
| §1.7 RBAC roles | 6 — `Licensee` (`entity_backed:Client`), `SalesManager`, `EventServicesManager`, `SettlementAnalyst`, `FacilitiesPlanner`, `VenueAdmin`; role model `segregation_of_duties` |
| §1.8 difficulty instances | 26 across all 9 rules (≥2 each) |
| §1.9 corner instances | 107 total = 78 full recipes + 29 `excluded_because` stubs |

§1.9 per-section breakdown: entities 12, state_machines 15, calculations 13, validations 9, endpoints 6, errors 34, rbac 9, cross_cutting_complexity_layers 7, consistency_model 2.

### Verified invariants beyond the lint

- All 67 catalogued errors are referenced by at least one §1.8 or §1.9 instance (13 of them via `excluded_because` stubs that cite a §1.8 instance by exact name; every cited name resolves).
- No duplicate `name` within §1.9 and none across §1.8 ∪ §1.9 (133 unique names).
- No instance carries a key outside `{name, claim_type, grounds, distinguishing_aspect, test_recipe, excluded_because}`.
- All nine `section:` values come from the claim-extraction-guide; errors-section instances use `claim_type: violation_to_error` per the SKILL.md §1.9 example (Table 6 has no claim-type rows).
- Forbidden concurrency vocabulary ("simultaneously", "at the same time", "concurrently submitted", "in parallel", "first-writer-wins", "race winner/loser") is absent from all three files.
- The hard constraint was honoured: no sibling `tasks/task_*/` directory was listed, globbed, grepped, or read; the only inputs were the scenario text and the generator skill's own `SKILL.md`, `references/claim-extraction-guide.md` and `scaffold_lint.py`.

Difficulty above expert level comes mainly from: a threshold-plus-half-day-factor rental formula whose settlement twin is round-per-day-then-sum (a one-cent divergence that a sum-then-round implementation gets wrong, and which validation 93 rejects), a three-band separately-rounded union labour charge, a capped multiplicative surcharge stack over marginal utility tiers, a re-selecting facility fee tier where a *lower* subtotal can yield a *higher* fee, `ServiceOrder`'s two independent state dimensions, cyclic amendment/dispute loops with lifetime round caps that survive the round trip, closed-interval hold conflicts across a self-referential space hierarchy, buffer-day blackout clearance, and a segregation-of-duties gate that sits at priority 46 ahead of both dispute-window gates.

## Step 3: Copy shared files — 2026-09-01T00:22:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2250_convention_center_booking_event_services/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T00:38:00.000Z

Verification complete. All three Hard Contracts pass.

### PRD delivered

`workspace/PRD.md` — **483 lines, ~13,980 words**. Ends at §5 with no audit footer. Constraint honored: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no other `task_*/` directory was read.

### Structure

- **§1 Introduction** — 3 paragraphs: citywide/local/consumer-show demand conflict, the commercial lifecycle the API governs, and the two technical constraints (logical clock, integer-cent arithmetic).
- **§2 Global Specifications** — 12 subsections: 2.1 RBAC and the six roles; 2.2 API Response Structure (verbatim contract block); 2.3 Pagination and Collection Filtering; 2.4 Common Resource Properties; 2.5 The Server Logical Clock; 2.6 Money, Crew-Hours and Rounding Discipline; 2.7 The Space Tree and Interval Arithmetic; 2.8 Stale-Version Guards; 2.9 Conserved Counters and Cascade Discipline; 2.10 Order Posture; 2.11 Validation Precedence and Left-to-Right Path Resolution; 2.12 Segregation of Duties.
- **§3 Business Logic** — 10 domain-derived subsections (venue registry -> tentative booking -> hold hierarchy -> license/DEFINITE -> event services -> union labor -> F&B exclusivity -> in-house ops -> settlement/arbitration -> maintenance windows).
- **§4 Endpoint Definitions** — 80-row, 4-column table.
- **§5 Error Code Catalogue** — 67-row, 2-column table.

### Coverage audit

| Scaffold element | Count | Covered |
| --- | --- | --- |
| Entities | 15 | 15 (incl. the two `id`+`created_at`-only append-only records) |
| Entity fields | 111 | 111 |
| State machines | 9 machines / 10 entity-dimension pairs | all |
| Transitions | 44 | 44 (each with explicit `FROM -> TO` notation) |
| Calculations | 11 (3 with two variants each) | 11 / all 14 variant paths |
| Validations | 49 | 49, in exact priority order 10->98 |
| Concurrency rules | 2 | 2 |
| Endpoints | 80 | 80 (48 with side-effect sets, all narrated) |
| Errors | 67 | 67 (all also named in §2/§3 prose) |
| Roles | 6 | 6, each with identity semantics stated |
| Named constants | 27 + 5 in-text | all present |

### Hard Contract reports

```
Field coverage check:
- entities[].fields: 111 required, 111 present, 0 missing
- endpoints[].request_body: 71 required, 71 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 49 checked, 49 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 49 checked, 49 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 48 checked, 48 expressed, 0 missing
- entities[].fields[] structured content: 111 checked, 111 reconstructible from prose, 0 missing
- sibling-branch symmetry: 13 groups checked, 13 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 918
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Notable derivations recorded in prose

- **`order_posture`** is declared by the scaffold but never defined; §2.10 states an explicit three-rule derivation consistent with every listed recompute side effect, and pins which six operations require `OPEN` versus the one (reconcile) that `RESTRICTED` still permits.
- **Buffered maintenance windows** are defined once in §2.7 as strict separation on both sides (equivalently, intersection with the window extended by `buffer_days`), then reused by booking creation, hold placement, and blackout approval.
- **Cascade asymmetry preserved**: blackout approval releases bookings reaching `hold_count` 0 while `TENTATIVE` **or** `DEFINITE`; the hold sweep and answer-challenge release only `TENTATIVE` ones. Called out explicitly so it cannot be read as an editing slip.
- **Rounding orders pinned** where they change the integer: per-usage-day rounding before summing and before the class discount; per-band rounding before summing the three labor bands; round-then-floor on service-order and buyout minimums; fee band keyed on subtotal, never on grand total.
- **State guards on related entities** carry that entity's `*_STATE_INVALID` code, per a convention stated in §2.11 step 9 and instantiated at each site (e.g. confirm-definite with no `CONFIRMED` hold -> `ERR_HOLD_STATE_INVALID`; license terminate on a booking past `DEFINITE` -> `ERR_BOOKING_STATE_INVALID`).

## Step 5: Generate unit tests — 2026-09-01T01:20:00.000Z

Test infrastructure and suite are complete.

### Files written

**Stage 1 — `test_helpers/` (9 files, 2,459 lines)**
`__init__.py` (barrel), `types.py`, `api_errors.py` (67 error ids + `HTTP_STATUS_CODES` + `set_error_http_status_map`), `constants.py`, `test_users.py`, `api_client.py` (one method per all 80 endpoints), `factories.py`, `assertions.py`, `fixtures.py` (readers, atomic builders, and `setup_event_lifecycle` with 11 stages).

**Stage 2 — `test_suite/` (conftest + 18 test modules, 6,375 lines, 144 tests)**

| File | Tests | Source |
|---|---|---|
| test_01_rental_and_labor_variants.py | 4 | queue A `dual_variant_calc` |
| test_02_combinatorial_formulas.py | 6 | queue A `combinatorial_formula` |
| test_03_lifecycle_state_machines.py | 6 | queue A `non_linear_state_machine` |
| test_04_transitive_cascades.py | 6 | queue A `transitive_cascade` |
| test_05_validation_precedence.py | 6 | queue A `priority_pair_validation_conflict` |
| test_06_boundary_precision.py | 6 | queue A `boundary_precision_check` |
| test_07_cross_entity_dependencies.py | 6 | queue A `cross_entity_state_dependency` |
| test_08_temporal_overlap.py | 6 | queue A `resource_temporal_overlap` |
| test_09_conserved_ledgers.py | 6 | queue A `compensating_invariant` |
| test_10_entity_shapes.py | 10 | queue B `entities` |
| test_11_state_transitions.py | 11 | queue B `state_machines` |
| test_12_calculation_corners.py | 9 | queue B `calculations` |
| test_13_validation_corners.py | 6 | queue B `validations` |
| test_14_endpoint_corners.py | 4 | queue B `endpoints` |
| test_15_error_corners_a.py | 23 | queue B `errors` (first half) |
| test_16_error_corners_b.py | 10 | queue B `errors` (second half) |
| test_17_role_and_ownership.py | 14 | queue B `rbac` |
| test_18_concurrency_and_consistency.py | 5 | queue B `cross_cutting` + `consistency_model` |

### Coverage

- **Queue A (§1.8):** 26/26 difficulty instances, every one at exactly 2 tests. No gaps.
- **Queue B (§1.9):** 107 instances, 29 of them `excluded_because:` stubs (never translated). 74 of the 78 non-stub instances covered; 4 skipped.

### Instances skipped (all four for the PRD-first filter, none weakened or placeholdered)

1. `entities/booking_creation_with_an_unknown_event_class_value_rejected` — asserts 400 `ERR_INVALID_REQUEST` *and explicitly not* 422 `ERR_POLICY_WINDOW_MISSING`, but PRD §2.11 puts the policy-window lookup above generic body validation ("This check deliberately precedes generic body validation..."), so the PRD derives 422.
2. `entities/child_space_creation_with_an_unknown_parent_space_id_not_found` — §2.11 step 5 enumerates the endpoints where body-reference existence yields 404, and `POST /spaces` with `parent_space_id` is not among them; no PRD sentence pins any code.
3. `endpoints/blackout_approve_releases_colliding_holds_only_where_it_collides` — asserts the Ballroom B booking stays `TENTATIVE` with `hold_count == 0`, but §3.10 says a booking whose `hold_count` reaches 0 while `TENTATIVE` **moves to `RELEASED`**. Salvageable upstream if that one assert is corrected.
4. `rbac/licensee_reading_another_clients_license_rejected` — §2.1 enumerates exactly five ownership-checked operations; neither `GET /licenses/{id}` nor `GET /clients/{id}` is among them and §4 authorises `Licensee` on both, so the PRD derives 200, not `ERR_NOT_RESOURCE_OWNER`.

**One sub-assertion omitted** (instance otherwise kept): in `boundary_precision_check/client_standing_threshold_at_exactly_ten_million_outstanding_stays_good`, the design asserts `order_posture == OPEN` on a `SETTLED` booking, which PRD §2.10 rule 1 contradicts (`LOCKED` when status is `SETTLED`). The instance's core boundary claim — standing stays `GOOD` at exactly 10,000,000 cents outstanding — is asserted.

### Verification passed

`py_compile` and `pyflakes` clean on all 19 suite files; all `from test_helpers import` names resolve against the barrel; `pytest --collect-only` collects 144 tests with no import errors; every test carries exactly one trailing `Design:` line resolving to a real non-stub instance name (no untagged, dual-tagged or stub-tagged tests); all 263 PRD quotes verified verbatim against `workspace/PRD.md`; no `skip`/`xfail`/mocking anywhere; nothing under `test_helpers/` modified by the queue-B subagents; no other `task_*/` directory was read.

## Step 6: Generate implementation — 2026-09-01T01:20:00.000Z

All three smoke suites pass and the endpoint surface matches the SCAFFOLD exactly (80 declared = 80 implemented, no missing/extra). Implementation is complete.

### Files written
Root: `workspace/implementation/`

- Infra: `app.py` (59), `start.sh` (15, executable), `requirements.txt` (`flask>=3.0`)
- Core: `errors.py` (112, ~70 error ids -> HTTP status), `clock.py` (37, logical clock pinned to `2026-08-01T00:00:00Z`), `db.py` (71, in-memory `Store`/`Database`, nothing seeded), `util.py` (119, date/instant math), `response.py` (60, envelope + pagination meta), `validate.py` (121), `middleware.py` (150, auth/role ladder, `touch`, filters), `lookups.py` (159, 404 mapping + space-tree/child lookups), `calc.py` (223, every pinned Decimal/ROUND_HALF_UP formula + constants)
- Engine: `services/engine.py` (418) — hold ranking, cascades, conserved counters, settlement finalize
- Routes (10 blueprints, 80 endpoints): `routes/__init__.py`, `common.py`, `registry.py` (17), `bookings.py`, `holds.py`, `licenses.py`, `service_orders.py`, `labor.py`, `catering.py`, `settlements.py`, `blackouts.py`, `ops.py`

**Total 3293 LOC** (3277 Python). **80 endpoints**, all under `/convention-center`.

### Verification performed
- Fresh boot via `bash start.sh` on `0.0.0.0:$PORT` (default 10000): empty stores, clock at epoch, `401 ERR_UNAUTHENTICATED` without headers; a restart returns totals to 0, so `--isolation per-test-server` is safe.
- Three in-process suites exercised: envelope/meta regex + pagination bounds (0/101/-1/non-numeric -> 400); rental pricing (4.5 space-days -> 4,500,000 gross -> 3,825,000 contracted -> 956,250 deposit); ancestor `committed_space_days` roll-up; deposit escrow in/out; license draft->issue->countersign->amend->accept; hold ranking, challenge/answer with challenger release cascading a booking to RELEASED; hold sweep counters (1/1/1/1) and re-rank; blackout conflict 409 then approve, plus buffered-window rejection/clearance; utilities tier pricing (255,000), labor estimate/actual with OT, F&B buyout ESTIMATED 250,000 -> ACTUAL 440,000 at close; full settlement cycle (ACTUAL_USAGE basis 14,400,000, fee tier MID 1,050,000, dispute x3, revision limit 409, escalate -> arbitrate-finalize) with the depth-4 cascade: settlement FINAL -> booking SETTLED/LOCKED -> client outstanding + HOLD_RESTRICTED -> sibling booking LOCKED -> new bookings refused.

### Ambiguities resolved
- **`committed_space_days` propagation** — the pseudo-code increments only `space_id` but the field is defined as an aggregate over self+descendants; I charge the booking's space **and every ancestor**.
- **`version` bumps** coalesced to at most one increment per entity per request (`g.touched`), so the PRD's literal "+1" holds even inside deep cascades.
- **Timestamps** — entity `created_at`/`updated_at` use the logical clock; `meta.api_request_timestamp` uses real wall-clock UTC.
- **Ordering** — lists by `(created_at, seq)`; hold re-rank by `(hold_rank, created_at)` per the pinned rule, never by id; usage records by `(usage_date, created_at)`.
- **Ladder details** — path entity resolved before ownership (404 beats `ERR_NOT_RESOURCE_OWNER`); body FK absent/non-string -> 400, present-but-unresolvable -> that entity's 404; missing OCC field -> 400, mismatch -> 412.
- **Release scope by trigger** — voluntary hold release cascades no booking; answer-challenge and sweep release TENTATIVE bookings only; blackout approval releases TENTATIVE **and** DEFINITE. Only DRAFT/ISSUED licenses are voided on release (an EXECUTED license survives and keeps its escrow), matching the transition text.
- **Blackout approve asymmetry** — the conflict guard consults DEFINITE/IN_HOUSE bookings on *related* spaces, while hold releases sweep *self + descendants*.
- **open-show** checks license EXECUTED (step 9) before `ERR_MOVE_IN_NOT_REACHED` (step 15).
- **confirm-first-option** evaluates the release deadline before the rank check; challenge guard order is hold-state -> `ERR_CHALLENGE_NOT_PERMITTED` -> `ERR_CHALLENGE_LIMIT_REACHED`.
- **Catering** — `PATCH` left ungated by status (PRD declares neither guard nor error code); `approve` checks exception reason before exclusivity and does not re-check COI (priority-50 `applies_to` omits it).
- **Settlement** — `ERR_NO_USAGE_RECORDS` gated to ACTUAL_USAGE only; issue order = state -> booking CLOSED (first issue only) -> revision limit -> usage records -> rental-line match (which also covers "no lines"); finalize recomputes only `grand_total_cents`; fee tier always keyed on `line_subtotal_cents`.
- **Line items** — non-ADJUSTMENT amounts must be strictly positive, and no append may drive the prospective subtotal to <= 0.
- **Union hours** written by recomputing the conserved sum rather than incremental deltas; per-day capacity gate inclusive.
- **RBAC** — the endpoint `roles` list is authoritative wherever it disagrees with a transition's single `actor` field (e.g. both SalesManager and VenueAdmin may release).

## Step 7: Run tests and iterate — 2026-09-01T01:52:00.000Z

All 8 parallel rounds pass 144/144.

**Iterations run:** 2 (initial diagnostic sweep + one verification sweep after fixes).

**Baseline:** 129/144 in all 8 rounds, with an identical 15-test failure set every round — fully deterministic, no flakiness signal.

**Tests deleted:** none. Every failing test survived STEP 1 (PRD verbatim coverage) and STEP 1b (unique derivability); all 15 failures traced to test-layer defects, not to PRD silence.

**Fixes applied to `test_suite/` (13 tests, one mechanical defect):**
- `test_02_combinatorial_formulas.py`, `test_03_lifecycle_state_machines.py`, `test_05_validation_precedence.py`, `test_06_boundary_precision.py`, `test_07_cross_entity_dependencies.py`, `test_08_temporal_overlap.py` — 16 call sites referenced `ApiErrorId.ERR_<NAME>` while `test_helpers/api_errors.py` declares the enum members *without* the `ERR_` prefix (`ApiErrorId.RENTAL_LINE_MISMATCH`, value `"ERR_RENTAL_LINE_MISMATCH"`). Every one raised `AttributeError` during collection of the assertion, so the tests errored before reaching the server. Rewrote the references to the declared member names. This is semantics-preserving: the enum's `.value` — the `error_id` string actually asserted against the response — is unchanged, so no assertion was weakened.

**Fixes applied to `test_helpers/`-equivalent fixture logic (1 fixture, 2 tests):**
- `test_suite/test_06_boundary_precision.py`, local fixture `_settlement_totalling_exactly_the_standing_threshold` — the fixture appended the 149,533-cent `ADJUSTMENT` line *after* `setup_event_lifecycle(..., "settlement_issued")` had already issued the settlement. PRD §3.9 states verbatim: *"appending one does not recompute any settlement total — totals move only when the settlement is issued."* A PRD-faithful server therefore correctly left `line_subtotal_cents` at 12,000,000, and the two dependent tests (`test_finalization_totals_exactly_ten_million_after_applying_escrow`, `test_outstanding_balance_exactly_at_the_threshold_leaves_standing_good`) could never see their intended 12,149,533 subtotal / exactly-10,000,000 grand total. Switched the fixture to `setup_event_lifecycle`'s existing `extra_lines=[("ADJUSTMENT", 149533)]` parameter, which appends before the issue. Both assertions kept their exact expected cent values — the precondition was corrected, not the expectation.

**Fixes applied to `implementation/`:** none. No implementation defect was found; every failure was a test-artifact bug, and no PRD-required check was removed or relaxed.

**Orchestrator verification:** the Step 7 subagent left no `results.*.json` on disk, so the orchestrator re-ran the full 8-round parallel sweep itself. Result: rounds 1–8 all `144 / 144 failed=0`. `results.{1..8}.json` are now present in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-09-01T01:58:00.000Z

`workspace/PRD_FINALIZED.md` is written.

### Counts

- PRD.md: 482 lines / 13,977 words / 101,193 bytes
- PRD_FINALIZED.md: 482 lines / 14,055 words / 101,689 bytes
- Line-count delta: **0 lines (0.0%)** — 1 line revised in place (+78 words, +0.49% bytes). Total diff: 1 changed line.

### Changes

- **§3.9 (SettlementLineItem append paragraph, line 299)** — revise — added two clarifications to the existing append rules: (a) appending a line carries no settlement-state guard, so an append against an `ISSUED`, `DISPUTED`, `ARBITRATION` or `FINAL` settlement is accepted and leaves the stored totals as they stand; (b) the "may not drive the subtotal to zero or below" rule reads the *running sum of `amount_cents` over the already-appended lines plus the new line*, not the stored `line_subtotal_cents` — `implementation/routes/settlements.py:67-95` (checks at :78-82), `implementation/calc.py:207-209`.

### Per-edit pre-edit search log

**Edit 1 — §3.9 line-item append**

(a) Subject identified: the `POST /convention-center/settlement-line-items` append operation — which settlement states permit it, what `ERR_LINE_AMOUNT_INVALID` compares against, and what (if anything) an append does to the settlement's stored money fields. Traces to the Step 7 fixture fix in `test_06_boundary_precision.py::_settlement_totalling_exactly_the_standing_threshold`, whose defect was precisely that the post-issue append was *accepted* (201) yet moved no total, leaving `line_subtotal_cents` at 12,000,000 instead of 12,149,533.

(b) Impl paths enumerated (grepped `line_item|LINE_AMOUNT|recompute_settlement_totals|settlement_line_extension|line_subtotal` across all of `implementation/`, then read each hit):
- `routes/settlements.py:67-95` `append_line_item` — the only creation path for a line; role `SettlementAnalyst`; `body_fk` -> `ERR_SETTLEMENT_NOT_FOUND`; **no `settlement["status"]` guard anywhere in the handler**; check 1 = non-`ADJUSTMENT` and `amount <= 0`; check 2 = `existing + amount <= 0` where `existing` is re-summed live from the line table (applies to every `line_kind`, not just `ADJUSTMENT`); `db.insert(..., versioned=False)`; the settlement row is never `touch()`ed.
- `calc.py:207-209` `settlement_line_extension` — sums `amount_cents` over lines ordered `created_at`, `_seq`; used both by the append guard and by totalling, so the two read the identical basis.
- `lookups.py:127-128` `line_items_of_settlement` — unfiltered by status.
- `services/engine.py:371-382` `recompute_settlement_totals` — the *only* writer of `line_subtotal_cents` after creation; called from exactly one site, `routes/settlements.py:142` (issue / re-issue). Confirms "totals move only when the settlement is issued" for the subtotal and fee.
- `services/engine.py:385-409` `finalize_settlement` — recomputes `grand_total_cents` from the *stored* subtotal and fee (never re-sums lines) plus `deposit_applied_cents`; `routes/settlements.py:191-214` both finalize doors.
- `routes/settlements.py:31-49` `open_settlement` — initializes all four money fields to 0.
- `routes/settlements.py:115-153` `issue_settlement` — the rental-line composition checks that read the same line population (`ERR_RENTAL_LINE_MISMATCH`, the other Step 7 site).

(c) Wording adjustments made to stay consistent with all enumerated paths:
- Original draft said an appended line "sits there until some later issue recomputes the totals" — wrong for a `FINAL` settlement, which has no later issue. Re-scoped to "is accepted and simply leaves that settlement's stored totals as they stand".
- Deliberately did **not** strengthen the pre-existing verbatim clause "totals move only when the settlement is issued" into a universal claim about all stored totals, because `finalize_settlement` does move `deposit_applied_cents` and `grand_total_cents` outside issue (already described later in §3.9).
- Phrased the sign-rule basis as covering every append (not only `ADJUSTMENT` appends), matching check 2's unconditional placement.
- Did not add any claim about the settlement's `version`/`updated_at` on append (impl does not touch it); §2.4's "mutation of that resource" wording already covers it and a new claim would exceed the traced scope.

### Items deliberately left unpatched

- **Enum-prefix fix (16 call sites, 6 test files)** — pure test artifact: `AttributeError` at assertion-construction time meant those requests' responses were never compared. The fix changed no assertion value (`ApiErrorId.RENTAL_LINE_MISMATCH.value == "ERR_RENTAL_LINE_MISMATCH"`), and the impl paths behind each id (verified for the settlement-composition ladder: revision limit -> `ERR_NO_USAGE_RECORDS` -> `ERR_RENTAL_LINE_MISMATCH`, `routes/settlements.py:126-139`) already match §2.11 steps 16-17 and §3.9 verbatim. No PRD silence revealed, so no edit.
- **The fixture's PRD anchor itself** ("appending one does not recompute any settlement total") — already verbatim in PRD.md and matched by impl; kept unchanged.

## Step 9: Complete PRD — 2026-09-01T02:18:00.000Z

### Files

| | lines | chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` (source) | 482 | 101,689 |
| `workspace/PRD_COMPLETED.md` | 484 | 116,479 |

Char delta: **+14,790** (+14.5%). Line delta: **+2** (one new paragraph inside the existing §2.11; no new sections, no new headings, no changes to §4 Endpoint Definitions or §5 Error Code Catalogue).

### Counts

- **ambiguity-pins: 70**
- **mismatch-revisions: 7**
- total changes: 77, spread over 44 diff hunks in §2.1–§2.11 and §3.1–§3.10

### Changes

**§2.1** — revise — ambiguity — an empty header value counts as absent, and the role compare is exact/case-sensitive — `implementation/middleware.py:39`
**§2.1** — insert — ambiguity — `X-User-ID` is any non-empty string, never shape-checked — `implementation/middleware.py:36`
**§2.2** — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `implementation/response.py:20`
**§2.2** — insert — ambiguity — `api_request_timestamp` is taken from the host wall clock, not the logical clock — `implementation/response.py:27`
**§2.2** — revise — ambiguity — pagination meta appears only on list endpoints — `implementation/response.py:41`
**§2.2** — insert — ambiguity — sweep and clock-set return a computed object in `data`, not a resource — `implementation/routes/ops.py:19,31`
**§2.3** — insert — ambiguity — non-integer/out-of-range `limit`, negative `offset` -> 400; over-large offset is legal and empty — `implementation/middleware.py:107`
**§2.3** — revise — ambiguity — `has_more` = `offset + len(page) < total_count` — `implementation/response.py:45`
**§2.3** — revise — ambiguity — `created_at` ties break by insertion order (common, since the clock is logical) — `implementation/db.py:35`
**§2.3** — insert — ambiguity — filters are exact string compares; unknown params ignored; null/boolean match rules — `implementation/middleware.py:136,145`
**§2.4** — revise — ambiguity — `id` is a canonical hyphenated UUIDv4, unprefixed — `implementation/db.py:53`
**§2.4** — revise — ambiguity — `created_at` from the logical clock; same-instant creations share it — `implementation/db.py:51`
**§2.4** — insert — ambiguity — `updated_at` likewise from the logical clock — `implementation/middleware.py:85`
**§2.4** — insert — ambiguity — `version` increments at most once per record per request — `implementation/middleware.py:88`
**§2.5** — insert — ambiguity — `to_iso8601` required string; unparseable -> 400; naive read as UTC; backwards allowed — `implementation/routes/ops.py:26`
**§2.5** — revise — ambiguity — `current_utc` rendered with three fractional digits — `implementation/routes/ops.py:31`
**§2.9** — insert — ambiguity — counter movement charges the space *and* every ancestor, each touched; siblings untouched — `implementation/services/engine.py:76`
**§2.10** — revise — **mismatch** — dropped the claim that `RESTRICTED` simply permits reconciliation; a booking-state guard narrows it — `implementation/routes/service_orders.py:152`
**§2.10** — insert — ambiguity — posture re-derived per request from live status/standing; stored row refreshed only on a real change — `implementation/services/engine.py:35`
**§2.11** — insert — ambiguity — malformed reference (absent/null/non-string/empty) -> 400 at the reference step; optional `parent_space_id` skipped when null — `implementation/routes/common.py:36`
**§2.11** — insert — ambiguity — framework rejections: unmatched path -> 404 `ERR_BOOKING_NOT_FOUND`; bad method -> 405; unparseable body -> 400; absent body = `{}` — `implementation/app.py:31`, `implementation/middleware.py:71`
**§3.1** — revise — ambiguity — deposit `amount_cents` is an integer >= 1 — `implementation/routes/registry.py:65`
**§3.1** — insert — ambiguity — `outstanding_balance_cents` re-derived as the whole aggregate (may fall); unchanged re-derivation is a no-op — `implementation/services/engine.py:46`
**§3.1** — insert — ambiguity — space area and rate are required non-negative integers — `implementation/routes/registry.py:81`
**§3.1** — insert — ambiguity — jurisdiction shift edges are ints 0–24 and unchecked against each other; rate int; three parameters may be fractional — `implementation/routes/registry.py:186`
**§3.1** — revise — ambiguity — jurisdiction PATCH is partial, always bumps `version`, and may lower capacity below hours already committed — `implementation/routes/registry.py:223`
**§3.1** — revise — ambiguity — `rental_discount_pct` is a number in [0,1); outside -> 400 — `implementation/routes/registry.py:117`
**§3.1** — insert — ambiguity — the six other window parameters are required integers with stated bounds, and body validity precedes `ERR_POLICY_WINDOW_EXISTS` — `implementation/routes/registry.py:117`
**§3.2** — revise — ambiguity — `event_name` required non-empty; `expected_attendance` a non-negative integer when supplied — `implementation/routes/bookings.py:33`
**§3.2** — insert — ambiguity — the whole-months formula (12*dyear + dmonth, minus 1 when the day of month is smaller; may go negative) — `implementation/util.py:90`
**§3.2** — revise — ambiguity — creation charges `committed_space_days` to the space and every ancestor — `implementation/services/engine.py:76`
**§3.2** — revise — **mismatch** — release is open to both roles from either `TENTATIVE` or `DEFINITE`; the roles are not paired to states — `implementation/routes/bookings.py:219`
**§3.2** — revise — ambiguity — the release cascade also zeroes `estimated_charge_cents` on orders that were `ESTIMATED` — `implementation/services/engine.py:200`
**§3.3** — insert — ambiguity — `expected_booking_version` required integer validated before any comparison; placement ungated on booking status/posture — `implementation/routes/holds.py:23`
**§3.3** — revise — ambiguity — the deadline month-shift clamps the day of month (31st -> 28/29/30) — `implementation/util.py:81`, `implementation/services/engine.py:415`
**§3.3** — revise — ambiguity — a hold is created at `version` 1 with `hold_rank` written as part of creation — `implementation/routes/holds.py:23`
**§3.3** — insert — ambiguity — rank ordering breaks `created_at` ties by insertion order — `implementation/services/engine.py:123`
**§3.3** — insert — ambiguity — a released hold keeps its `hold_rank` and, if `CHALLENGED`, its challenge fields — `implementation/services/engine.py:133`
**§3.3** — revise — ambiguity — `challenger_hold_id` required non-empty string, then resolved as `ERR_HOLD_NOT_FOUND` — `implementation/routes/holds.py:105`
**§3.3** — revise — **mismatch** — either hold not `ACTIVE` (including a `CONFIRMED` challenger) -> `ERR_HOLD_STATE_INVALID`, not `ERR_CHALLENGE_NOT_PERMITTED` — `implementation/routes/holds.py:112`
**§3.3** — revise — ambiguity — the sweep is two ordered passes; the second reads state as the first left it — `implementation/services/engine.py:221`
**§3.3** — revise — ambiguity — exact definition of each of the four counters; idempotent (four zeroes on a re-run); plain-object response — `implementation/services/engine.py:221`
**§3.3** — revise — ambiguity — voluntary release requires `ACTIVE`, else `ERR_HOLD_STATE_INVALID` — `implementation/routes/holds.py:187`
**§3.3** — insert — ambiguity — voluntary release never cascades to the booking even at `hold_count` 0 — `implementation/services/engine.py:133`
**§3.4** — insert — ambiguity — drafting takes no body and no booking status/posture guard; only *issue* requires `TENTATIVE` — `implementation/routes/licenses.py:25`
**§3.4** — revise — ambiguity — both amendment fields required with stated shapes, checked before every guard — `implementation/routes/licenses.py:102`
**§3.4** — revise — ambiguity — the booking-state check runs with the license-state check, ahead of the version and round guards — `implementation/routes/licenses.py:102`
**§3.4** — revise — ambiguity — accept takes no body, resets the round fields, and leaves `executed_at_utc` alone — `implementation/routes/licenses.py:126`
**§3.4** — revise — ambiguity — accept's reprice is inert: no endpoint revises a booking's four dates, so the money fields stand as created — `implementation/routes/licenses.py:126`
**§3.4** — revise — **mismatch** — order cancellation on void belongs to the booking release, so it happens identically for `DRAFT` and `ISSUED` (and with no license at all); voiding itself only moves the deposit — `implementation/services/engine.py:187,159`
**§3.5** — revise — ambiguity — `estimated_quantity` is a number strictly above zero and may be fractional — `implementation/routes/service_orders.py:27`
**§3.5** — revise — ambiguity — with several exclusive vendors registered, any one of them satisfies exclusivity — `implementation/routes/service_orders.py:27`
**§3.5** — insert — ambiguity — exclusivity is judged at order time and not re-judged at approval, where only the insurance date is re-read — `implementation/routes/service_orders.py:95`
**§3.5** — revise — ambiguity — `actual_quantity` required number strictly above zero, possibly fractional — `implementation/routes/service_orders.py:147`
**§3.5** — revise — ambiguity — the usage factor comes from the `order_timing` frozen at creation, never re-derived — `implementation/calc.py`
**§3.5** — revise — ambiguity — both reconcile state requirements (`APPROVED` and `ESTIMATED`) report `ERR_SERVICE_ORDER_STATE_INVALID` — `implementation/routes/service_orders.py:149`
**§3.5** — insert — **mismatch** — the `IN_HOUSE` guard is evaluated before the posture gate, so a `RESTRICTED` booking can never reconcile — `implementation/routes/service_orders.py:151`
**§3.6** — revise — ambiguity — `crew_size` is an integer of at least 1; fractional rejected — `implementation/routes/labor.py:21`
**§3.6** — insert — ambiguity — `billed_hours` and the day's running total are each quantized to one decimal, half up, before comparison — `implementation/calc.py:77`
**§3.6** — revise — ambiguity — dispatch needs the booking to stand exactly `IN_HOUSE`, so `CLOSED` is refused — `implementation/routes/labor.py:97`
**§3.6** — insert — ambiguity — actual hours are required numbers constrained only by ordering, not by the 0–24 range — `implementation/routes/labor.py:115`
**§3.6** — insert — ambiguity — the capacity re-check excludes the call being actualized, and the work date is not re-checked against the event span — `implementation/services/engine.py:346`
**§3.7** — revise — ambiguity — `guest_count` is an integer of at least 1 — `implementation/routes/catering.py:28`
**§3.7** — revise — ambiguity — `actual_fnb_cents` is a required integer >= 0 on its own endpoint — `implementation/routes/catering.py:126`
**§3.7** — insert — ambiguity — that revision carries no state guard, is repeatable, and reprices nothing itself — `implementation/routes/catering.py:126`
**§3.7** — insert — **mismatch** — close silently skips an `APPROVED` arrangement whose `actual_fnb_cents` is null rather than failing; other statuses untouched — `implementation/routes/bookings.py:205`
**§3.8** — revise — **mismatch** — open-show has three guards in a fixed order, with the license check ahead of the move-in date check — `implementation/routes/bookings.py:170`
**§3.8** — insert — ambiguity — attestation is ungated by booking status, posture, and the licensed interval; only the per-date uniqueness rule applies — `implementation/routes/bookings.py:247`
**§3.9** — revise — ambiguity — `settlement_basis` is a required enum; absent or misspelled -> 400 — `implementation/routes/settlements.py:24`
**§3.9** — revise — ambiguity — one settlement per booking whatever that settlement's status, so a `FINAL` one still blocks a successor — `implementation/routes/settlements.py:24`
**§3.9** — insert — ambiguity — line-item field shapes; `source_ref_id`/note optional strings that need not resolve — `implementation/routes/settlements.py:69`
**§3.9** — revise — ambiguity — `dispute_reason` required non-empty, validated ahead of the status and deadline checks — `implementation/routes/settlements.py:158`
**§3.9** — insert — ambiguity — the escrow license fallback chain (live -> last holding a deposit -> last of any status -> deposit 0) — `implementation/lookups.py:150`
**§3.9** — insert — ambiguity — finalize does not recompute `line_subtotal_cents` or `facility_service_fee_cents` — `implementation/services/engine.py:385`
**§3.9** — revise — ambiguity — the booking move and everything downstream fire only when the booking actually stands `CLOSED`; otherwise escrow still draws down — `implementation/services/engine.py:404`
**§3.10** — revise — ambiguity — `buffer_days` optional non-negative integer, default 2; 0 legal and reduces clearance to plain non-intersection — `implementation/routes/blackouts.py:25`
**§3.10** — revise — ambiguity — `active_blackout_count` is tallied on the named space only, never on ancestors or descendants — `implementation/services/engine.py:283`

Nothing in the source PRD was deleted outright and no behavior was described that the implementation does not exhibit; every insert is anchored to a specific code path listed above.
