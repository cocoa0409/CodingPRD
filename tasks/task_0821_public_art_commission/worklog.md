# Worklog — task_0821_public_art_commission

Scenario: Public Art & Percent-for-Art Commission: capital-project percent budget, artist call (RFQ/RFP), selection panel & scoring, contract & fabrication milestone, installation & site, conservation/maintenance registry, deaccession, loan/donation

Difficulty: Expert

## Step 1: Create task directory — 2026-07-10T13:28:50.663Z

Created `tasks/task_0821_public_art_commission/` and `tasks/task_0821_public_art_commission/workspace/` (pre-assigned directory; no index auto-scan).

## Step 2: Generate scaffold — 2026-07-10T13:55:00.000Z

All checks pass. The scaffold package is complete and self-consistent.

## Summary

Generated a three-file Expert-difficulty scaffold for **task_0821_public_art_commission** at `/home/ubuntu/github/CodingPRD/tasks/task_0821_public_art_commission/`:

- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top key)

**Complexity profile:** Multi-party negotiation (primary) + Quota/allocation (secondary); hybrid topology; compound/cyclic/parallel state shapes; peer_roles; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.

**Scaffold contents:**
- **13 entities:** CapitalProject, Commission, ArtistCall, Artist, Submission, Panelist, Score, Contract, Milestone, Site, Artwork, ConservationRecord (append-only), Loan.
- **9 state machines:** including the Submission revision cycle (SUBMITTED↔REVISION_REQUESTED), Artwork parallel dimensions (location_status × condition_status), Site cyclic AVAILABLE↔OCCUPIED, and cascade-driven Contract/Commission/Artwork auto-transitions.
- **5 calculations:** art_budget_computation (dual-variant provisional/final), submission_composite_score (weighted 4-criterion + trimmed-vs-mean variant + durability-floor gate), milestone_allocation (pinned round-per-line-then-remainder), budget_ledger, contract_payment_ledger. Every constant (rates, W_*, DURABILITY_FLOOR, TRIM_MIN, LOAN_BUFFER_DAYS=30) is declared with a concrete value.
- **20 validations** (priority-ordered across 8 categories), **46 endpoints** (incl. `POST /_clock/set_current_utc` with the mandated 2026-03-01T00:00:00Z default), **31 errors**, **4 roles** (ProgramAdmin/Registrar opaque; Artist/Panelist entity_backed), **2 concurrency rules** (OCC on CapitalProject.version and Contract.version).

**§1.8:** 18 instances — 2 per each of the 9 Difficulty Rules, each with structured `setup_api_calls`/`trigger`/`assert` chains and formula-derived literal asserts (e.g., composite 69.00 trimmed vs 69.92 mean; milestone remainder 333335; budget/quorum boundaries).

**§1.9:** 29 instances (25 full recipes + 4 `excluded_because` stubs) spanning all nine claim-extraction sections (entities, state machines, calculations, validations, endpoints, RBAC, cross-cutting layers, consistency).

**Verification:** all three files pass `yaml.safe_load`; `scaffold_lint.py` reports **VERDICT: clean lint** (276 calls scanned); no forbidden concurrency vocabulary; all 47 instance names globally unique; all `grounds` refs and stub `difficulty_instance` refs resolve. Two computed back-pointers (`Commission.awarded_submission_id`, `Site.current_artwork_id`) were deliberately worded as denormalized pointers (not `FK ->`) since they need no reverse-reachability GET.

Per the hard constraint, no sibling `task_*/` directories were read — the design was derived solely from the scenario and the scaffold-generator skill spec.

## Step 3: Copy shared files — 2026-07-10T13:57:15.358Z

Copied `./INSTRUCTION.md` → `tasks/task_0821_public_art_commission/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-10T14:03:30.000Z

All three hard contracts pass. The PRD is complete.

## Summary

Generated `/home/ubuntu/github/CodingPRD/tasks/task_0821_public_art_commission/workspace/PRD.md` (283 lines) from the scaffold, without opening either withheld design file or any sibling task.

**Sections written:**
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications — 9 subsections: 2.1 Access Control & Actor Identity, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Properties & Versioning, 2.5 Precision & Rounding, 2.6 Optimistic Concurrency Control, 2.7 Budget/Payment Ledger Invariants, 2.8 Logical Clock & Temporal Rules, 2.9 Nested Resolution & Validation Ordering
- §3 Business Logic — 7 subsections (projects/budget, commissions/award/contract, calls/panels/submissions, scoring/tabulation, fabrication cascade, registry/sites/conservation, loans/deaccession)
- §4 Endpoint table (4 columns) and §5 Error table (2 columns)

**Coverage (mechanically verified):**
- **Endpoints: 46 documented = 46 in scaffold** ✓ (46 rows in §4 table)
- Field-name coverage (Contract 1): 65 required identifiers, 0 missing — all entity fields, request-body/query/path params including `expected_project_version`, `expected_contract_version`, `milestones`, `to_iso8601`, `sequence`, `pct`
- Errors: all 31 error IDs appear in §2/§3 narrative (not only the §5 table)
- Validations: all 20 covered, with priority orderings stated in prose (auth → authz → ownership → existence → state → business guards, and the conflict-before-duplicate ordering on scoring)
- Calculations: all 5 rendered as precise prose with every constant's concrete value (percent bounds 0.005/0.01/0.05, score weights 0.40/0.25/0.20/0.15, DURABILITY_FLOOR 40, TRIM_MIN 3, 30-day loan buffer, dual-variant art budget, waterfall milestone rounding, both ledger invariants)
- State machines: all 9 covered, including the fabrication cascade chain (milestone PAID → Contract COMPLETED → Artwork FABRICATED → Commission FULFILLED), the cancel cascade, the revision cycle, and the parallel Artwork location/condition dimensions
- Concurrency (Contract 2): both OCC rules stated with write endpoint + expected-version field + `ERR_STALE_VERSION` + HTTP 412
- §3 Path Purity (Contract 3): 334 backtick tokens scanned in §3, 0 path/method violations

**Hard Contract reports: Contract 1 PASS, Contract 2 PASS, Contract 3 PASS.**

Orchestrator verification: `yaml`-cross-checked all 46 scaffold endpoint paths and all 31 error IDs appear verbatim in PRD.md. PRD endpoint count == scaffold endpoint count.

## Step 5: Generate unit tests — 2026-07-10T14:20:00.000Z

All checks pass. Here is the summary.

## Summary

Generated complete test infrastructure and suite for `task_0821_public_art_commission`, driven exclusively by the two design indices.

### Files written

**`test_helpers/`** (Stage 1, 9 files):
- `types.py` — 13 entity TypedDicts + 12 status/enum classes. `ConservationRecord` correctly carries only `id`/`created_at` (common_fields: false); all others carry `updated_at`/`version`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (47 endpoints).
- `api_errors.py` — `ApiErrorId` enum + `HTTP_STATUS_CODES`, registered with the framework.
- `assertions.py` — per-entity assertions + `assert_budget_invariant` / `assert_payment_invariant`.
- `factories.py`, `constants.py`, `test_users.py` (opaque ProgramAdmin/Registrar shared constants; `make_artist_headers`/`make_panelist_headers` builders for the two entity-backed roles), `fixtures.py` (composite builders with automatic project/contract version threading), `__init__.py` barrel.

**`test_suite/`** (Stage 2, 6 files): `conftest.py` + `test_01_projects_and_budget.py`, `test_02_selection_and_scoring.py`, `test_03_contracts_and_milestones.py`, `test_04_registry_and_loans.py`, `test_05_cascades_and_access.py`.

### Test count: 57 tests

All 15 files parse; all 57 collect under pytest; every PRD citation verified verbatim against `workspace/PRD.md` (whitespace-normalized grep, 0 failures); every `Design:` tag resolves to a real instance (0 dual/untagged/dangling).

### Coverage
- **Difficulty (queue A):** 16 of 18 instances translated, each with ≥2 tests.
- **Corner (queue B):** all 25 non-stub instances translated (≥1 test each); the 4 `excluded_because:` stubs left untranslated, all cross-references resolve.

### Skipped instances (2, both from `priority_pair_validation_conflict`)
- **`state_beats_fiscal_on_commission_create`** — asserts creating a commission against a `DRAFT` (uncertified) project yields `ERR_INVALID_STATE`. The PRD never states that commission creation requires a `BUDGET_CERTIFIED` project (only contract *activation* does, §3.5), so the outcome fails the PRD-coverage condition; it is also a validation-priority "A-beats-B" test with no PRD-stated precedence.
- **`referential_beats_temporal_on_submission_create`** — asserts duplicate-submission wins over past-deadline. PRD §3.3 states both errors but never commits to an ordering when both fire, so the outcome is not uniquely derivable (validation-priority silence pattern).

Both gaps are left as gaps per the design-index-only contract — no weakened or placeholder tests emitted.

## Step 6: Generate implementation — 2026-07-10T14:20:00.000Z

All checks pass. The implementation is complete and verified.

## Summary

Built a complete Python + Flask in-memory REST API for the Public Art / Percent-for-Art Commission task in `/home/ubuntu/github/CodingPRD/tasks/task_0821_public_art_commission/workspace/implementation/`.

### Files written
- `start.sh` — foreground launcher, guarded `pip install` (only when Flask missing), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — Flask
- `app.py` — creates the app, registers 3 blueprints, `ApiError`/404/405 handlers
- `db.py` — in-memory dicts (13 entity tables), logical clock (default `2026-03-01T00:00:00Z`), monotonic insertion sequence. No seeding.
- `util.py` — response envelope (`meta`/`response_type`/`data`), error catalog, auth+RBAC, `Decimal` round-half-up helpers, ISO-8601 (3-digit ms) time + parser, pagination
- `serialize.py` — per-entity serializers; computed fields (`committed`/`uncommitted`/`paid`/`remaining`) resolved on read; `ConservationRecord` carries only `id`+`created_at`
- `routes_budget.py` — projects, commissions, contracts, milestones
- `routes_selection.py` — calls, panelists, artists, submissions, scores, tabulation
- `routes_registry.py` — sites, artworks, install/deaccession/conservation, loans, clock

### Verification
- All 7 `.py` files pass `ast.parse`
- **Route count = 46** (matches scaffold/PRD), verified via `app.url_map`
- `bash start.sh` boots and serves within seconds

End-to-end behavior exercised and confirmed correct: provisional/final art-budget rounding, OCC stale-version (412) + budget-ceiling (422), waterfall milestone allocation (remainder on highest sequence, sums exact), full payment cascade (milestone PAID → contract COMPLETED → artwork FABRICATED → commission FULFILLED with version/updated_at bumps), install/site-occupancy + freeing on deaccession, loan 30-day buffer conflict (409), deaccession-blocked-by-approved-loan (409), composite score **trimmed** vs **mean** variants, durability-floor disqualification, quorum-not-met (409), panelist-conflict (422), duplicate-submission (409), deadline-passed (422), ownership (403), and pagination meta on list endpoints. Milestone-schedule correctly returns 201.

Storage is entirely in-memory and starts empty on every boot, satisfying the per-test-server restart contract.

Orchestrator verification: `app.url_map` route count == 46 == scaffold endpoint count (no partial-write gap); 57 tests across 5 test files.

## Step 7: Run tests and iterate — 2026-07-10T14:35:00.000Z

All 8 rounds pass 57/57.

## Summary

**Iterations run:** 2 sweeps (1 diagnostic, 1 confirming the fix).

**Root cause:** Two tests in `test_suite/test_03_contracts_and_milestones.py` asserted mathematically incorrect expected milestone amounts. The author treated `pct = 0.3333` as if it meant exactly `1/3`. The PRD rule (§3.5, line 168) says `amount_cents = contract_amount_cents × pct` rounded half-up to whole cents. With `contract_amount_cents = 1000001` and `pct = 0.3333`, the correct value is `1000001 × 0.3333 = 333300.3333 → 333300`, not `333333`. The implementation (`routes_budget.py` `schedule_milestones` + `util.round_half_up_cents`) was already PRD-correct.

**Tests deleted:** None. Both failures were STEP 2 test-assertion bugs (assertion mis-translates the PRD rule applied to the given inputs), not PRD-silence — so the assertions were corrected to faithfully express the PRD rule, not deleted.

**Fixes applied to `test_suite/test_03_contracts_and_milestones.py`:**
- `test_milestone_amounts_use_pinned_rounding`: corrected expected amounts to seq1=333300, seq2=333300, seq3=333401 (final absorbs the +1 rounding remainder; natural 0.3334 value would be 333400).
- `test_final_milestone_absorbs_rounding_remainder`: corrected seq3 expectation from 333335 to 333401. The `sum == 1000001` assertion was already correct.

**Fixes applied to `implementation/`:** None — the implementation was correct.

**Final state:** 8/8 rounds pass, 57/57 tests each, no flakiness.

Orchestrator verification: re-read all 8 `results.{1..8}.json` (passed==total==57 in every round). Independently recomputed the PRD milestone formula with Decimal ROUND_HALF_UP: seq1=333300, seq2=333300, seq3-natural=333400, seq3-as-remainder=333401, sum=1000001 — confirming the corrected expectations are PRD-derived, not back-fitted to implementation output.
