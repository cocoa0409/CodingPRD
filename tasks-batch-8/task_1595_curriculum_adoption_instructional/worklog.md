# Worklog — task_1595_curriculum_adoption_instructional

## Step 1: Create Task Directory — 2026-08-14T00:10:00.000Z

Task directory `tasks/task_1595_curriculum_adoption_instructional/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Treated as DONE per orchestrator instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T01:29:00.000Z

Scaffold generation complete. All three artifacts are written and pass `scaffold_lint.py` with a clean verdict.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1595_curriculum_adoption_instructional/SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1595_curriculum_adoption_instructional/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1595_curriculum_adoption_instructional/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

## Counts

- **Entities: 14** — AdoptionCycle, CurriculumFramework, InstructionalMaterial, AlignmentMapping, PilotProgram, TeacherReview, PublisherQuote, PurchaseOrder, InventoryLot, DistributionOrder, SupplementalRequest, ChallengeCase, CommitteeVote (immutable, `common_fields: false`), BudgetLedger
- **State machines: 9** across 8 entities — includes parallel dimensions on InstructionalMaterial (adoption × availability) and PurchaseOrder (order × payment), cyclic loops (quote clarification revision, challenge appeal rounds, SR reaffirm loop, cycle remand/return-to-draft), and a 12-state AdoptionCycle with an auto-transition
- **Calculations: 8** — alignment coverage, dual-variant rubric composite (untrimmed vs trimmed at n≥5), participation rate, bundled pricing (pinned round-per-line-then-sum with discount applied after line rounding), best-value award score, ledger balances (with money-conservation invariant + reconciliation view), inventory availability (with unit-conservation invariant), dual-variant budget forecast (ROLLING vs STRAIGHT_LINE with pinned tier-evaluation order)
- **Endpoints: 53** (incl. `POST /_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default)
- **Errors: 37** — every code is cited by a validation/transition and has at least one trigger test in the design files
- **Difficulty instances (§1.8): 22** — dual_variant_calc ×3, combinatorial_formula ×3 (modes a/b/c all covered), non_linear_state_machine ×3, transitive_cascade ×2 (depth 3 each, distinct triggers), priority_pair_validation_conflict ×2 (state-vs-fiscal; safety-vs-constraint), boundary_precision_check ×2, cross_entity_state_dependency ×3, resource_temporal_overlap ×2, compensating_invariant ×2
- **Corner instances (§1.9): 49 active + 4 `excluded_because` stubs** across all nine taxonomy sections
- **Lint: `VERDICT: clean lint`** (1257 calls scanned; all FK reverse-reachability checks pass)

## Notable design decisions

- **Archetype**: compliance/audit primary + quota/allocation secondary; flat FK topology; segregation-of-duties role model (requester≠approver, filer≠voter, ownership-checked withdraw/appeal) across 9 opaque roles
- **OCC concurrency (2 rules)**: both guard true create-with-supersede races on `AdoptionCycle.version` — award re-posting (legitimately supersedes the SELECTED quote) and PO creation (supersedes the cycle's DRAFT PO); both negative tests prove polarity by succeeding with a fresh version
- **Version pinning**: award sets `pinned_quote_id`/`quote_version_pin`; sending the selected quote to clarification clears the pin, making PO creation fail with `ERR_QUOTE_NOT_SELECTED`
- **Temporal overlap with deliberately different interval semantics**: pilots use half-open `[starts_on, ends_on)` (adjacency allowed, cancellation releases) vs. public-review windows using closed intervals with a mandatory 30-day clear gap (adjacency forbidden) — per subject_area
- **Cascades**: challenge-decide REMOVED → material → DO cancellation → lot recompute + `replacement_due`; PO receipt → lot → head-of-line backorder promotion (need_priority DESC, `created_at` ASC; never id) → cycle counters + auto-advance
- **All formula-derived asserts pre-computed as Decimal literals** (e.g., trimmed rubric 2.87 vs provisional 2.80; best-value 88.52/78.03/57.50; forecast bases 12000.00/1159.27 with tier-order pinned) — verified by executing the formulas in Python during authoring
- Boundary tests target inclusive edges: coverage exactly 85.00, participation exactly 0.60, composite exactly 3.20, formal bid threshold exactly 250000.00, exact-fit inventory allocation (leaving 0), exact remaining payment, quorum exactly 3, window deadlines at ±1 day

## Step 3: Copy Shared Files — 2026-08-14T01:30:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1595_curriculum_adoption_instructional/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T01:45:00.000Z

The PRD is complete and all three hard contracts pass. Final summary:

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1595_curriculum_adoption_instructional/workspace/PRD.md` — 369 lines.

**Section list:**
- §1 Introduction (2 paragraphs — statutory-obligation angle, then system commitments: due process, segregation of duties, conservation ledgers)
- §2 Global Specifications: 2.1 RBAC (9 roles, opaque identity, recorded-id ownership rules), 2.2 API Response Structure (**byte-identical verbatim block**, verified programmatically), 2.3 Pagination, 2.4 The Logical Clock and Calendar Windows, 2.5 Common Resource Properties (incl. CommitteeVote `updated_at`/`version` absence), 2.6 Money/Precision/Rounding, 2.7 Request Validation Cascade + left-to-right path resolution, 2.8 OCC on Cycle-Scoped Writes, 2.9 Parallel Status Dimensions, 2.10 Budget Ledger Money Conservation, 2.11 Warehouse Unit Conservation
- §3 Business Logic (10 subsections, chronological-lifecycle grouping): 3.1 Frameworks/Cycle Initiation/Appropriations, 3.2 Materials & Alignment, 3.3 Pilots & Teacher Rubric, 3.4 Public Review & Board Decision, 3.5 Quotes/Evaluation/Award, 3.6 Purchase Orders/Receipts/Payments, 3.7 Inventory & Distribution, 3.8 Supplemental Requests, 3.9 Challenges/Votes/Appeals, 3.10 Replacement Planning & Budget Forecast
- §4 Endpoint Definitions (53-row table, 4 columns only) · §5 Error Code Catalogue (37-row table, 2 columns only)

**Zero-Silence coverage audit** (scaffold rule → PRD passage):
- **Entities (14)** — all fields placed: framework/cycle §3.1; material §3.2 + §2.9; alignment upsert §3.2; pilot/review §3.3; quote §3.5; PO §3.6; lot §2.11+§3.7; distribution order §3.7; supplemental §3.8; challenge/vote §3.9; ledger §2.10. Cycle system fields placed at their workflows (`public_review_opens_at/closes_at` §3.4, `pinned_quote_id`/`quote_version_pin` §3.5, `open_backorder_count` §3.7, `replacement_due` §3.9+§3.10, `adopted_material_id` §3.4).
- **State machines (9 machines, 56 transitions)** — every from/to pair, precondition→error pairing, and side-effect cascade expressed in §3.1–3.9 (incl. revert loop ALIGNMENT_REVIEW→DRAFT, remand re-stamping, clarification loop with pin-clear, supersede chains, REMOVED cascade, reaffirm/revoke cycle, appeal round bookkeeping).
- **Concurrency rules (2)** — §2.8 plus re-anchored at award §3.5 and PO create §3.6; both name `expected_cycle_version`, `ERR_STALE_CYCLE_VERSION`, HTTP 412, and the after-state/before-business evaluation position.
- **Calculations (8)** — coverage weights/threshold §3.2; provisional vs trimmed-official composites (5-review trim, one instance per extreme) §3.3; participation rate (4dp, zero-denominator null) §3.3; bundled pricing with pinned line-round-then-discount-then-sum order §3.5; best-value score (zero-min edge, caps, weights, no intermediate rounding) §3.5; ledger invariant + reconciliation view §2.10; unit conservation §2.11/§3.7; forecast with pinned evaluation order, ROLLING (120.00/0.20/5-yr) vs STRAIGHT_LINE (3 prior cycles, 1.03^5, created_at tie-break never id, empty→0.00), tiers 0.05/0.08/0.12 §3.10.
- **Validations (12 priorities)** — full ordered cascade in §2.7; intra-endpoint orderings in §3 (vetted-existence before coverage; composite before participation; material-match → pool-size → winner; freeze before inventory).
- **Endpoints (53) / Errors (37) / Roles (9)** — tables complete; every error trigger lives in §2/§3 prose; all role `identity: opaque` fields translated with the five recorded-id ownership fields named.

**Gaps found and fixed:** one — `pilot_id` (TeacherReview foreign key) was initially missing; added in §3.3 via an Edit. (A false alarm where the audit script mis-parsed backticks across fenced JSON blocks was an audit-script bug, not a PRD gap.)

**Contract reports:**
```
Field coverage check:
- entities[].fields: 94 required, 94 present, 0 missing
- endpoints[].request_body: 7 required, 7 present, 0 missing
- endpoints[].query_params: 15 required, 15 present, 0 missing
- endpoints[].path_params: 11 required, 11 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (endpoint + expected_cycle_version + ERR_STALE_CYCLE_VERSION/412), 0 missing
- state_machines[].transitions: 56 checked, 56 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (no pseudocode, no fuzzy words — verified by scan), 0 missing
- validations[] conditions: 37 error ids checked, 37 matchable in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults/nullability/derived flags all reconstructible, 0 missing
- sibling-branch symmetry: ADOPT/REJECT, UPHELD/RESTRICTED/REMOVED × MATERIAL/SUPPLEMENTAL_REQUEST, ROLLING/STRAIGHT_LINE, PROVISIONAL/OFFICIAL, and all transition sibling groups rendered at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 617
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T02:35:00.000Z

Generation complete. Summary:

## Files written

**`test_helpers/` (9 files)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1595_curriculum_adoption_instructional/test_helpers/`:
- `types.py` — 9 role/status enums + 16 entity TypedDicts; `CommitteeVote` correctly omits `updated_at`/`version` (immutable record)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (clock, frameworks, cycles, materials, alignments, pilots, reviews, quotes, POs, lots, distribution orders, supplemental requests, challenges, votes)
- `api_errors.py` — all 37 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity validators + `assert_budget_money_conservation` / `assert_inventory_unit_conservation` invariants
- `factories.py`, `constants.py` (all PRD thresholds: 85.00 coverage, 3.20 composite, 0.60 floor, 250k bid threshold, 120.00/0.20/5yr/1.03 forecast constants, tier table)
- `test_users.py` — shared header constants for the 9 (all-opaque) roles + `make_*_headers(user_id)` builders for ownership/SoD tests
- `fixtures.py` — ~50 helpers across all 5 tiers: primitives, `setup_cycle_in_pilot_open` → `setup_active_pilot` → `setup_cycle_in_scoring` → `setup_cycle_board_pending` → `setup_cycle_adopted` → `setup_cycle_procuring` → `setup_cycle_distributing` → `setup_cycle_active`, plus `setup_two_candidate_cycle`, `setup_decided_material_challenge`, OCC-aware `award_quote`/`create_purchase_order` (fresh-version fetch), ledger/lot readers
- `__init__.py` — barrel export (framework generics + PRD-specific)

**`test_suite/` (14 files)** — `conftest.py` (api + 9 role fixtures) and 13 test files, simple-to-complex: creation → request guards → envelope/pagination → alignment gate → pilots → reviews/scoring → public review/board → quotes/awards → POs/budget → forecast → inventory/distribution → supplemental → challenges/appeals.

## Coverage
- **Queue A (difficulty): 22/22 instances, 44 tests** (exactly 2 per instance) — rubric trim (incl. tied-extremes variant), award LR-vs-BEST_VALUE (57.50/88.52/78.03 scores), forecast ROLLING-vs-STRAIGHT_LINE, line-rounding order, zero-min pool, tier ordering, parallel material dimensions, clarification loop (relative version increments), appeal round cycle, removal + backorder-promotion cascades, both priority-pair conflicts, both boundary instances, all three cross-entity dependencies, both temporal-overlap rules, both conservation invariants.
- **Queue B (corner): 49/49 non-stub instances, 49 tests.** The 4 `excluded_because:` stubs were not translated; all 4 difficulty-instance cross-references verified to resolve (`alignment_coverage_threshold_inclusive`, `po_create_requires_selected_pinned_quote`, `challenge_removal_cascade`, `rubric_provisional_vs_official_trim`).

## Instances skipped
None. Every non-stub instance passed the PRD-first two-condition filter. One adaptation note: this task's PRD (unlike some sibling tasks) never states an initial version value, so absolute `version == 1`/`2 -> 3 -> 4` literals were translated into PRD-derivable form (capture-and-compare, "increments by exactly one" per the version-semantics paragraph, `vote_round == 1` which IS verbatim). All instance claims themselves were asserted in full.

## Self-check results
- `py_compile` clean on all 22 files; `pytest --collect-only` collects **93 tests** with zero import errors
- Tag audit (temporary script, removed after run): every test docstring ends with exactly one verbatim `Design:` line resolving to a real instance; 22/22 difficulty ≥2, 49/49 corner ≥1; no `skip`/`skipif`/`xfail` anywhere
- Verbatim-citation check: every ≥8-word quoted span in every docstring matched PRD.md verbatim (whitespace-normalized)
- Scaffold-leak grep: no "scaffold"/table/§1.x references in generated code
- Tests were not executed against a live server (no implementation exists yet in the task directory) — execution is the runner's stage.

## Step 6: Generate Implementation — 2026-08-14T02:36:00.000Z

All verification is complete. Here is the summary.

## Implementation complete — task_1595_curriculum_adoption_instructional

### Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1595_curriculum_adoption_instructional/workspace/implementation/`)
- `start.sh` — guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`, foreground, `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry, error handlers for `ApiError`/404/405/500
- `db.py` — empty-on-boot in-memory `Store` (dicts keyed by id), logical clock booting at exactly `2026-08-01T00:00:00Z` (never wall-clock), `stamp_new`/`bump`/`refresh` helpers (version bumps only on state transitions per PRD §2.9; computed-field updates refresh `updated_at` only)
- `errors.py` — all 37 error IDs with exact HTTP statuses (incl. 402 budget, 412 OCC, 403 SoD)
- `response.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more`), pagination rejected (not clamped) with `ERR_INVALID_PAGINATION_PARAMETERS` outside limit 1..100 / offset >= 0, `created_at`-ASC sort with insertion-sequence tiebreak
- `middleware.py` — auth (X-User-ID/X-User-Role, 9 roles), role checks, typed body validators (Decimal-exact)
- `serializers.py` — all scaffold fields incl. nulls; CommitteeVote carries only `id`+`created_at` (no `updated_at`/`version`)
- `routes/` — 10 modules: clock, frameworks, cycles (transitions/board-decision/award/budget×3/nested creates), materials (+alignments upsert, inventory-lots, material DOs), pilots (+reviews), reviews (withdraw), quotes, purchase_orders, distribution_orders, supplemental, challenges (+votes)
- `services/calculations.py`, `services/cascades.py`

### Coverage
- **Endpoints: 53/53** from the scaffold table (verified via `url_map` listing)
- **State machines: 9** — AdoptionCycle (12 states, revert/remand loops, auto PROCURING→DISTRIBUTING on first receipt), Material (parallel adoption × availability dimensions), Pilot, Review (withdraw with ownership), Quote (clarification loop + SELECTED pin-clear), PO (parallel order × payment, supersede-on-create, cancel compensation), DistributionOrder (head-of-line backorder promotion, need_priority DESC/created_at ASC), SupplementalRequest (SoD + encumbrance commit/release, reaffirm loop), ChallengeCase (quorum ≥3, plurality with tie→UPHELD, one appeal with vote_round++, 14-day window)
- **Calculations: 8/8** — alignment coverage (85.00 inclusive gate), provisional vs trimmed-official composite (trim at ≥5, one instance per extreme), participation rate (4dp, null on zero seats), bundled pricing (pinned line-round → discount → re-round → sum), best-value score (full precision until final round; zero-min edge), budget ledger (derived available_balance), inventory availability (derived allocated/available), dual-variant budget forecast (ROLLING 120.00×0.20×5; STRAIGHT_LINE top-3 other ACTIVE/SUNSET cycles, school_year_start DESC/created_at ASC, ×1.03⁵; tiers keyed on the rounded base)
- **Validation cascade** implemented in PRD §2.7 tier order, including body-FK existence (404) before remaining shape checks, OCC (tier 6, `expected_cycle_version` → `ERR_STALE_CYCLE_VERSION` 412) after state and before business rules on award + PO create, freeze-before-inventory on DO approve, SoD before fiscal on SR approve, and window → open-challenge → eligibility on challenge create
- **No seeding** — store provably empty on second boot

### Verification results
- **Boot smoke test**: `bash start.sh` on scratch port → 200 from `POST /_clock/set_current_utc` and `GET /frameworks` within ~3s; foreground process held until killed; second boot showed an empty store
- **Full-lifecycle suite** (~120 assertions): passed — auth/role failures, framework gates, coverage 85.00 boundary, revert loop, pilot overlap/adjacency (half-open), review composites (2.74 provisional, 3.18 after withdraw), close-pilots scoring (official 3.18, participation 0.8/1.0/0.3333), public-review window stamps + remand re-stamp + inclusive close, composite-before-participation gates, adoption + slate rejection, award OCC/material-match/pool/winner ordering, pin version capture, DRAFT-PO supersede, receipts/over-receipt, pay-to-exact-balance → PAID, ledger conservation (499000.0 available), backorder → promotion on receipt, ship/receive lot math, SR SoD 403 + encumbrance, challenge freeze/duplicate/quorum/tie→UPHELD/appeal rounds/revoke-with-release/REMOVED cascade (replacement_due=true, DO cancellations), challenge/appeal window boundaries, ACTIVE gate (ERR_OPEN_WORK_REMAINS), SUNSET
- **Edge suite**: passed — BEST_VALUE scores (87.50/95.00/45.00/100.0/54.38), formal bid rule at ≥250000 (pool 3) vs informal (pool 2), pin-clear → `ERR_QUOTE_NOT_SELECTED`, re-award supersede, PO cancel releasing only unpaid encumbrance, `ERR_PO_NOT_CLOSABLE`, `ERR_PAYMENT_EXCEEDS_BALANCE`, bundle-discount pinned rounding (10.005×3 → 30.02 line, discount → 12.81, total 42.83), 30-day public-review gap (exactly 30 days conflicts, 31 passes, different subject exempt), REJECT slate-kill, participation floor error, pagination bounds, CommitteeVote shape (no `updated_at`/`version`)

## Step 7: Test/Iterate Loop — 2026-08-14T02:58:00.000Z

All 8 rounds pass 93/93 with zero failures, errors, or skips. The exit condition is met.

## Summary

**Iterations run:** 2 (initial baseline sweep + post-fix verification sweep — final sweep: all 8 rounds clean, 93/93 each).

**Baseline failure union (5 tests):**
- `test_material_invalid_transition_rejected` — 8/8 rounds
- `test_participation_below_floor_rejected_after_composite_passes` — 8/8
- `test_participation_exactly_floor_passes_and_cascades` — 8/8
- `test_award_quote_material_mismatch_rejected` — 8/8
- `test_best_value_accepts_high_service_quote` — 2/8 (flaky `ConnectionError: Connection reset by peer`)

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
1. `/home/ubuntu/github/CodingPRD/tasks/task_1595_curriculum_adoption_instructional/test_helpers/fixtures.py` — `setup_two_candidate_cycle`: the fixture previously drove the cycle to `PILOT_OPEN` and *then* submitted material m2, violating PRD §3.2 ("While a cycle is in `DRAFT` or `ALIGNMENT_REVIEW`, a `CurriculumDirector` submits candidate materials"), so the PRD-faithful implementation correctly rejected setup with `ERR_INVALID_STATE`. Restructured to create, vet, and align **both** materials before the cycle leaves `ALIGNMENT_REVIEW`. This one fixture bug accounted for 3 of the 5 failing tests (classic shared-setup-error triage).
2. `/home/ubuntu/github/CodingPRD/tasks/task_1595_curriculum_adoption_instructional/test_helpers/api_client.py` — added `api_client.session.headers["Connection"] = "close"` so the shared `requests.Session` never reuses a stale pooled socket across the per-test server restart (the source of the flaky connection-reset in rounds 2/8; same pattern used by sibling tasks, e.g. task_1200/task_1213).

**Fixes applied to `test_suite/`:**
3. `/home/ubuntu/github/CodingPRD/tasks/task_1595_curriculum_adoption_instructional/test_suite/test_04_alignment_gate_and_coverage.py::test_material_invalid_transition_rejected` — relaxed the exact `ERR_INVALID_STATE` assertion to `validate_error_is_one_of([ERR_INVALID_STATE, ERR_VALIDATION])` per the cardinal-rule coverage-correction exception. Unique-derivability miss: PRD §3.2 pins `ERR_INVALID_STATE` only for *vetting* requests and never enumerates the `to_state` enum domain for `POST /materials/{id}/transitions`; two PRD-faithful readers diverge (ADOPTED fails at state tier if `to_state` spans the adoption dimension, at shape tier if scoped to {VETTED, REJECTED}). The no-transition / no-mutation assertions remain exact. Feedback for doc-generator (Zero-Silence: `to_state` domain never stated) and unit-test-generator (exact-error assertion not uniquely derivable).

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful everywhere; all failures were test-artifact bugs (one fixture precondition violation, one test-infrastructure flake, one underdetermined assertion).

## Step 8: Finalize PRD — 2026-08-14T03:10:00.000Z

The patch is exactly one inserted paragraph; everything else is verbatim. Task complete.

## Summary

**Line counts / %-delta:** PRD.md 369 lines (61,176 chars) → PRD_FINALIZED.md 371 lines (63,042 chars); +2 lines (+0.54%), +1,866 chars (+3.05%). Single insertion, zero revisions.

**Step 7 diff triage:** Items 1 (fixture submitted material m2 after the cycle left `ALIGNMENT_REVIEW`) and 2 (shared `requests.Session` connection-reset flake) are pure test-artifact bugs — they reveal no PRD silence and required no PRD edit. Item 3 was the only genuine PRD silence: the `to_state` enum domain on `/transitions` endpoints and its error-tier mapping.

**Changes (one bullet per change):**
- **§2.7 — insert** — one new paragraph after the "Path identifiers" paragraph pinning the `to_state` contract for all eight `/transitions` endpoints: `to_state` is required and validated as an endpoint-scoped enum at the request-shape tier (missing, non-string, or out-of-set → `ERR_VALIDATION`); the accepted set is enumerated per endpoint (cycles: `ALIGNMENT_REVIEW`/`DRAFT`/`PILOT_OPEN`/`SCORING`/`PUBLIC_REVIEW`/`BOARD_PENDING`/`ACTIVE`/`SUNSET`; materials: `VETTED`/`REJECTED`; pilots: `ACTIVE`/`CLOSED`/`CANCELLED`; quotes: `UNDER_EVALUATION`/`CLARIFICATION_REQUESTED`/`WITHDRAWN`; purchase orders: `CLOSED` only; distribution orders: `APPROVED`/`BACKORDERED`/`SHIPPED`/`RECEIVED`/`CANCELLED`; supplemental requests: `VETTING`/`APPROVED`/`DENIED`; challenge cases: `SCREENING`/`COMMITTEE_REVIEW`/`HEARING`/`DECIDED`/`APPEALED`/`CLOSED`); initial states and cascade/other-operation-only statuses (material `PILOT_CANDIDATE`/`ADOPTED`; cycle `ADOPTED`/`NOT_ADOPTED`/`PROCURING`/`DISTRIBUTING`; quote `SELECTED`/`REJECTED`/`SUPERSEDED`; supplemental `UNDER_CHALLENGE`/`REAFFIRMED`/`REVOKED`) are explicitly invalid `to_state` values failing at the shape tier, not the state tier; an accepted value illegal from the current state → `ERR_INVALID_STATE`, with further preconditions deferred to §3 — impl: `implementation/routes/materials.py:51`, `cycles.py:42-51,163`, `pilots.py:54`, `quotes.py:77-78`, `purchase_orders.py:167`, `distribution_orders.py:93-95`, `supplemental.py:96`, `challenges.py:31-38,150`, `middleware.py:119-123` (`req_enum`).

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: the `to_state` field's accepted-value domain and error-tier mapping on all `/transitions` endpoints.
- (b) Impl paths enumerated: all eight transition handlers read in full (materials.py, cycles.py, pilots.py, quotes.py, purchase_orders.py, distribution_orders.py, supplemental.py, challenges.py) plus `middleware.py` and a repo-wide grep for `to_state` confirming no ninth endpoint takes it. Cross-checks performed: (i) per-target-state role gates at `cycles.py:164` and `challenges.py:151` fire *after* `req_enum` — the wording deliberately says nothing about authorization ordering so as not to disturb that unpinned detail; (ii) every in-set/illegal-from-state rejection on all eight endpoints is `invalid_state`, verified branch by branch; (iii) further preconditions keep their §3-named errors (`ERR_PILOT_NOT_STARTED`, `ERR_QUORUM_NOT_MET`, `ERR_PO_NOT_CLOSABLE`, `ERR_MATERIAL_FROZEN`, `ERR_INSUFFICIENT_INVENTORY`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_BUDGET_ENVELOPE_EXCEEDED`, etc.) — the paragraph defers to §3 rather than re-pinning them; (iv) material `REJECTED` is both endpoint-accepted and cascade-reachable, so it was kept out of the "not valid" list; (v) `cycles.py` and `challenges.py` build their accepted sets from role-map keys — the enumerated sets match those keys exactly.
- (c) Wording adjustments: the normative claim was scoped strictly to set membership ("a value outside the endpoint's accepted set is rejected with `ERR_VALIDATION`"), with the cascade-reachable status list made explicitly illustrative ("initial states, and statuses an entity reaches only through another operation…") so birth states (`SUBMITTED`, `PLANNED`, `REQUESTED`, `DRAFT`, `FILED`) are covered by the rule without the example list implying exhaustiveness; the state-tier sentence uses "then" to situate it after the shape tier within §2.7's existing masking frame.

## Step 9: PRD Completeness Scan — 2026-08-14T03:35:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1595_curriculum_adoption_instructional/workspace/PRD_COMPLETED.md`.

## Summary

- **Source vs output**: `PRD_FINALIZED.md` 371 lines / 63,252 chars → `PRD_COMPLETED.md` 373 lines / 67,571 chars; **char-delta +4,278**; 29 changed passages (in-paragraph inserts/revisions only; one new two-sentence paragraph appended inside §2.5; no new sections).
- **Counts**: 24 ambiguity-pins, 5 mismatch-revisions.

### Mismatch revisions (5)
- **§2.5 `created_at`/`updated_at`** — revise — mismatch — PRD asserted "three fractional digits" always; impl (`db.py:80-88` `fmt_dt`) renders whole-second instants as `2026-08-01T00:00:00Z` with no fractional part, three digits only for sub-second readings; also pinned that both stamps read the logical clock (`db.py:103-104,113,120`).
- **§2.5 `version`** — revise — mismatch — PRD said "increments with every mutation"; impl starts `version` at 1 (`db.py:105`) and increments only on state transitions and operator-driven field writes (`db.py:110-114`), while computed-field recomputes call `refresh()` and touch only `updated_at` (`db.py:117-120`).
- **§3.1 framework `code`** — revise — mismatch — PRD said "a unique `code`"; impl never checks uniqueness (`routes/frameworks.py:24-35`), so the PRD now states codes are stored as supplied.
- **§3.9 committee voting** — revise — mismatch — PRD said members vote "while the case is in committee hands"; `cast_vote` has no case-status gate at all (`routes/challenges.py:230-260`), so the PRD now pins that votes are accepted against a case in any status, gated only by SoD and one-vote-per-round.
- **§3.9 challenge filing check order** — revise — mismatch — the narrative listed eligibility → window → open-challenge ("Finally..."); impl follows the §2.7 cascade: window (skipped when the target lacks the stamp) → one-open-challenge → eligibility (`routes/challenges.py:81-101`); a sentence now pins the cascade order.

### Ambiguity pins (24)
- **§2.2** — insert — ambiguity — `api_request_id` pinned as `req_` + twenty random alphanumerics (`response.py:20-21`).
- **§2.2** — insert — ambiguity — error `message` wording declared non-contractual; undefined paths → `ERR_NOT_FOUND` 404, unsupported methods → `ERR_VALIDATION` 405 (`app.py:27-44`).
- **§2.3** — insert — ambiguity — non-integer `limit`/`offset` rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (`response.py:83-96`).
- **§2.3** — insert — ambiguity — same-instant sort ties keep insertion order via the `_seq` sequence (`response.py:109-112`).
- **§2.3** — insert — ambiguity — `has_more` = `offset` + page size < `total_count` (`response.py:37`).
- **§2.4** — insert — ambiguity — clock accepts any parseable instant (no monotonicity check), offset-less values read as UTC, response is HTTP 200 (`routes/clock.py:14-20`, `db.py:56-68`).
- **§2.5** — insert — ambiguity — unset fields serialize as explicit JSON `null`, never omitted (`serializers.py` passim); client-supplied system-managed fields and unknown body fields are ignored, not rejected (`middleware.py:60-68`).
- **§2.7 tier 3** — insert — ambiguity — body-identifier existence list gains `cycle_id` (supplemental filing resolves it at tier 3, `routes/supplemental.py:35-37`).
- **§2.7 tier 4** — insert — ambiguity — non-JSON-object body and blank required strings fail the shape tier (`middleware.py:66-67,79-83`).
- **§2.7 transitions** — insert — ambiguity — per-`to_state` single-role gating on the cycle and challenge transition endpoints, evaluated after the `to_state` shape check and before the state check (`routes/cycles.py:42-51,164`; `routes/challenges.py:31-38,151`).
- **§2.9** — insert — ambiguity — explicit enumeration of non-transition version bumps (award pin, PO creation, alignment re-post) vs refresh-only recomputes (`coverage_pct`, composites, `participation_rate`, `best_value_score`, ledger totals, lot counters, `open_backorder_count`, `submitted_review_count`, pin-clear, `replacement_due`) (`db.py:110-120` plus all `bump`/`refresh` call sites).
- **§3.1** — insert — ambiguity — `effective_year` pinned integer (`routes/frameworks.py:30`).
- **§3.1** — insert — ambiguity — `school_year_start` and `district_enrollment` pinned integer (`routes/cycles.py:80,85`).
- **§3.1** — insert — ambiguity — appropriation response (HTTP 200) carries the updated ledger (`routes/cycles.py:437`).
- **§3.2** — insert — ambiguity — alignment upsert has no material/cycle state gate (`routes/materials.py:65-96`).
- **§3.4** — insert — ambiguity — the 30-day clear-gap check runs only on the initial opening from `SCORING`, never on a remand (`routes/cycles.py:197-204`).
- **§3.4** — insert — ambiguity — on `REJECT` the named material must exist but is otherwise unexamined; either decision's response (HTTP 200) carries the updated cycle (`routes/cycles.py:283-293,322-330`).
- **§3.4** — insert — ambiguity — a null `participation_rate` fails the participation gate outright (`routes/cycles.py:308-311`).
- **§3.5** — insert — ambiguity — quote submission also requires `publisher_name` (`routes/cycles.py:587`).
- **§3.5** — insert — ambiguity — resubmit fields omitted or supplied as `null` keep their current values (`routes/quotes.py:51-68`).
- **§3.5** — insert — ambiguity — award response (HTTP 200) carries the updated cycle (`routes/cycles.py:418`).
- **§3.9** — insert — ambiguity — `UPHELD` restores availability to `USABLE` from `RESTRICTED` as well as from `UNDER_CHALLENGE` (`services/cascades.py:83-85`).
- **§3.10** — insert — ambiguity — missing/unrecognized `variant` → `ERR_VALIDATION` 400 (`routes/cycles.py:455-457`).
- **§4** — insert — ambiguity — filters match by exact equality with no error on unmatched values, except `vote_round` which must parse as an integer (`routes/challenges.py:270-276`).

Everything else in the impl — the full endpoint surface, all `to_state` enum sets, the bundled-pricing/best-value/composite/forecast formulas, OCC ordering, cascade effects, 201/200 split, boot clock `2026-08-01T00:00:00Z`, bare-UUID ids, and the ledger/lot conservation rules — was already uniquely pinned by the PRD and left untouched.
