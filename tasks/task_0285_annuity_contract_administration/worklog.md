# Worklog — task_0285_annuity_contract_administration

## Step 1: Create Task Directory — 2026-06-11T00:00:00.000Z

Created pre-assigned task directory `tasks/task_0285_annuity_contract_administration/` with `workspace/` subfolder. Index scan skipped per pipeline instruction (5 entrance pipelines running in parallel; pre-assigned path used).

## Step 2: Generate Scaffold (EXPERT) — 2026-06-11T00:00:00.000Z

All three artifacts are complete, internally consistent, and pass `scaffold_lint.py` clean. Here is the final report.

Generated all three scaffold artifacts for `task_0285_annuity_contract_administration/` at **EXPERT** difficulty, purely from the scenario description and the scaffold-generator spec (no sibling tasks consulted). `scaffold_lint.py` reports **VERDICT: clean lint** across the package (372 §1.8+§1.9 calls conform to §1.5; all FKs reverse-reachable).

**Files written**
- `SCAFFOLD.yaml` (§1.0–§1.7 + §1.2.1)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** ledger_reconciliation (primary) + compliance_audit (secondary); layers dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency; hybrid topology; compound state shape; segregation_of_duties role model; `api_prefix: ""` (flat multi-collection surface).

**Entities (11):** Product, Contract, Premium, SubAccountAllocation, IndexSegment, CreditingEvent, Withdrawal, Beneficiary, Annuitization, DeathClaim, Exchange1035.

**State machines (9):** Contract (compound, 7 transitions incl. freeze/un-freeze + cascades), Premium (branching clear/reject), Withdrawal (branching settle/reject), Annuitization (branching), DeathClaim (branching fork-join verify+value→fund), Exchange1035 (cyclic SUBMITTED↔REVISION_REQUESTED + segregation of duties), plus IndexSegment, SubAccountAllocation, Beneficiary (terminal-state machines). Plus 3 OCC concurrency rules (Contract×2, Exchange1035×1).

**Key calculations (9):** chronological accumulation replay vs forward-looking projection (dual variant, inclusion-set divergence), free-corridor split, tiered surrender charge, signed MVA (pinned order corridor→charge→MVA), index/subaccount/fixed crediting (nested cap/floor/participation), death-benefit valuation (ROP/AV/HAV), beneficiary waterfall (remainder to created_at-earliest), annuitization monthly benefit (age-band × option tiers).

**Counts:** 19 validations, 20 errors, 55 endpoints (incl. 2 `/_clock` test-driving), 3 roles.

**§1.8 difficulty design:** 9 rule_ids × 2 instances = **18 instances** (all formula asserts pre-computed as literals, e.g. projection 2217436/2771795, gross withdrawal 307045, index credit 80000, beneficiary payouts 666800/666600/666600).

**§1.9 corner design:** 9 sections, **48 instances** (41 active test recipes + 7 `excluded_because` stubs citing real §1.8 instances).

Self-consistency verified beyond the linter: all `grounds` refs resolve, every error is referenced by a validation/concurrency rule, all instance names unique across both design files, enum closure holds, and no forbidden concurrency vocabulary appears in any of the three files. Fixed one latent formula inconsistency during authoring (death-benefit ROP/AV instance now reaches accumulation 1,800,000 via a free-corridor withdrawal rather than an impossible negative FIXED credit) and corrected an anniversary-roll `highest_anniversary_value` literal.

## Step 3: Copy INSTRUCTION.md — 2026-06-11T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0285_annuity_contract_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-11T00:00:00.000Z

Generated `workspace/PRD.md` (296 lines) from the Annuity Contract Administration scaffold.

**Section list:**
- **1. Introduction** (product families, ledger/concurrency tension)
- **2. Global Specifications & System-Wide Principles** (2.1 RBAC/3 roles, 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties — CreditingEvent common_fields:false, 2.5 Hierarchical Consistency & Cascades, 2.6 OCC — 3 rules + HTTP 412, 2.7 Money/Rates/Rounding, 2.8 Nested Retrieval & Existence Ordering, 2.9 Validation Ordering, 2.10 Logical Clock)
- **3. Business Logic & Workflows** (10 subsections: Products, Funding, Crediting 3 engines, Anniversary Roll, Withdrawals, Maturity Projection, Beneficiaries, Annuitization, Death Claims, 1035 Exchanges)
- **4. Endpoint Definitions** (all 55 endpoints)
- **5. Error Code Catalogue** (all 20 errors)

Hard contracts PASS: Field coverage 75/75; Rule coverage (validations priority chain, 3 OCC, all state-machine transitions incl. 3 sibling DeathClaim deny branches, 9 calculations, 20 error IDs, cascades) 0 missing; Path purity (§3) 0 path tokens. Confirmed: did NOT read either withheld design file.

## Step 5: Generate Unit Tests — 2026-06-11T00:00:00.000Z

Generated complete test infrastructure for **task_0285_annuity_contract_administration** entirely by translating the two design indices — no freelance walks of SCAFFOLD.yaml.

### Test counts
- **10 test files**, **75 tests total**
- **Queue A (§1.8 Difficulty): 36 tests** — all 18 instances covered by exactly 2 tests each (≥2 requirement met for every one of the 9 rules × 2 instances).
- **Queue B (§1.9 Corner): 39 tests** — covering 39 of the 41 non-stub instances (≥1 each).

### Instances SKIPPED under the PRD-first filter (2)
Both genuine PRD gaps, logged as inline `NOTE` comments (no skip/xfail):
1. `Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments` — asserts `Contract.version == cv1 + 1` after a withdrawal **create**, but PRD never states requesting a withdrawal bumps `Contract.version` (§3.5 says only *settle* increments). Fails unique derivability.
2. `Corner/entities/premiums_filtered_list_by_source_exchange_fk` — asserts `GET /premiums?source_exchange_id=` filters, but no PRD sentence states the endpoint accepts that query param. Fails coverage.

All 7 `excluded_because:` corner stubs correctly NOT translated; each stub's `difficulty_instance` cross-ref resolves to a real §1.8 instance.

### Audits passed
Every docstring ends with exactly one `Design:` line resolving to a real instance; every cited PRD sentence verified verbatim; no skip/skipif/xfail anywhere; all literal expected values copied verbatim from design YAMLs. `CreditingEvent` typed append-only (no version/updated_at); 3 roles modeled opaque; all files byte-compile and collect cleanly.

### test_helpers/ files written
`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` — plus `test_suite/conftest.py` and `test_suite/test_01..test_10`.

## Step 6: Generate Implementation — 2026-06-11T00:00:00.000Z

Built complete Python + Flask implementation at `workspace/implementation/`.

### Source files written (25)
- **Foundation**: `app.py`, `db.py` (in-memory store), `errors.py`, `response.py`, `middleware.py` (auth/RBAC), `validation.py`, `clock.py`, `requirements.txt`, `start.sh`
- **services/**: `contract.py` (chronological ledger replay, computed fields, cascades, freeze), `money.py` (Decimal round-half-up / floor), `lookups.py` (path-404 vs referenced-404)
- **routes/** (12 modules): products, contracts (incl. projection + 8 nested lists), premiums, allocations, index_segments, crediting_events, withdrawals, beneficiaries, annuitizations, death_claims, exchanges, clock_routes

### Endpoints: 55 implemented (matches PRD table exactly)

### start.sh / storage
Reads `$PORT` (default 10000), binds `0.0.0.0`, foreground `exec python3 app.py`, guards pip install on `import flask`. Storage in-memory only (dicts in `db.py`); no seeding — fresh boot reports `total_count: 0`.

### Verified behaviors (live)
Projection dual-variant (2,217,436/2,771,795), death-benefit ROP max 2,000,000, crediting cap/floor/participation, MVA 1,000, annuitization 10,800, anniversary roll, free-corridor split, OCC 412, segregation-of-duties 409, RBAC 403/401, path-404 vs referenced-404, OUTBOUND 1035 settle full-surrender cascade.

### Ordering subtleties resolved
1. Credit-period overlap checked before segment-OPEN state check.
2. Frozen-contract check before bare ACTIVE-state check on withdrawal/annuitization create + premium-clear/withdrawal-settle.
Note: `Product.surrender_charge_schedule` accepts non-negative `contract_year` (lookup by array index).

## Step 7: Run Tests and Iterate — 2026-06-11T00:00:00.000Z

All artifacts are in their final, correct state and the temp smoke-test file is removed. The benchmark is green.

**Iterations run:** 2 full 8-round parallel sweeps.
- Sweep 1: union of 2 failing tests (`test_initial_premium_below_minimum_rejected` failing in all 8 rounds; `test_insufficient_accumulation_on_settle` failing in 1 of 8 rounds — flakiness).
- Sweep 2 (after fixes): all 8 rounds pass 75/75, zero failures, zero errors.

**Tests deleted:** None. Both failures traced to a test bug and a transport-flakiness issue respectively, not to PRD-silence.

**Fixes applied to `test_suite/`:**
- `test_07_premiums_and_projection.py` → `test_initial_premium_below_minimum_rejected`: the test asserted the premium POST succeeds (201) and that `ERR_BELOW_MINIMUM_PREMIUM` fires at clear-time. This is inconsistent with PRD §3.2, where the rule — *"The initial premium's `gross_premium_cents` must be at least the product's `min_initial_premium_cents`, and falling short is rejected with `ERR_BELOW_MINIMUM_PREMIUM`"* — is stated in the **premium-submission** paragraph (the clearing paragraph never mentions this error). SCAFFOLD confirms `applies_to: "POST /premiums (when is_initial)"`. Per STEP 2, corrected the test to expect `ERR_BELOW_MINIMUM_PREMIUM` (422) on the `POST /premiums` call itself, and verified the contract stays `PENDING`. The implementation (which checks at submission) was already PRD-faithful and was left unchanged.

**Fixes applied to `implementation/`:**
- `app.py`: switched the server from the Werkzeug development server (`app.run(threaded=True)`) to `waitress.serve(app, threads=8)`, with a fallback to the dev server if waitress is unavailable. The round-5 `test_insufficient_accumulation_on_settle` failure was a transport-level `ConnectionError`/`BadStatusLine` on `POST /premiums/{id}/clear` during setup — the Werkzeug dev server dropping a connection under the 8x concurrent load of the parallel sweep. Waitress is a production-grade WSGI server that handles concurrent connections reliably; this is a transport-only change and alters no API behavior.
- `requirements.txt`: added `waitress==3.0.0`.
- `start.sh`: widened the dependency-presence gate from `import flask` to `import flask, waitress` so the new dependency is installed when missing.

No implementation logic, endpoints, response fields, or PRD-required checks were added, removed, or weakened. Storage remains in-memory only (plain dicts in `db.py`), wiped on every `start.sh` re-invocation.

## Step 8: Finalize PRD — 2026-06-11T00:00:00.000Z

`PRD_FINALIZED.md` produced. After applying the mandatory per-edit global search to every `<step_7_diff>` item, made **zero edits** — every item already uniquely determined by existing PRD prose or is a non-API-behavioral (transport/fixture) concern. Correct and expected outcome.

**Line counts:** PRD.md = 296; PRD_FINALIZED.md = 296. **Delta: 0 lines (0%).** Byte-identical (verified via `diff`).

### Per-item analysis of `<step_7_diff>`
- **Item A — test_suite fix (ERR_BELOW_MINIMUM_PREMIUM timing):** test bug, not PRD silence. PRD §3.2 (line 141) already states the rule verbatim in the premium-*submission* paragraph; clearing paragraph is silent; impl enforces at submission, matching PRD. No edit.
- **Item B — impl fix (waitress + requirements.txt + start.sh):** transport-only. PRD prose contains nothing about WSGI server choice, threading, port mechanics, dependency install, or persistence-across-restart. No API-observable behavior change. No edit.

### Pre-edit global search log
- **Subject 1 — ERR_BELOW_MINIMUM_PREMIUM / min_initial_premium_cents:** enumerated `errors.py:39`, `routes/premiums.py:76-83` (sole enforcement, at POST when is_initial), `routes/premiums.py:139-217` (clear — no minimum check), `routes/products.py:30,88,102` (store/serialize only). All consistent with existing prose. No wording adjustment.
- **Subject 2 — server transport/boot:** enumerated `app.py:90-101` (waitress.serve + dev-server fallback), `start.sh:7` (gate), `requirements.txt`, `db.py` (in-memory). PRD has no transport/boot/persistence prose. No edit.

## Step 9: Complete PRD — 2026-06-11T00:00:00.000Z

`PRD_COMPLETED.md` produced via full PRD-vs-implementation scan.

**File counts:** PRD_FINALIZED.md (source) = 296 lines / 47,418 chars; PRD_COMPLETED.md = 296 lines / 50,655 chars. Char delta **+3,237** (line count unchanged — all edits in-paragraph).

**Change counts:** 14 in-paragraph edits — 7 ambiguity-pins, 4 mismatch-revisions, plus related pins.

**Per-change bullets**
- §2.5 — insert — ambiguity — submitting a premium and requesting a withdrawal each bump `Contract.version` at create time — `routes/premiums.py:104`, `routes/withdrawals.py:99`
- §2.6 — revise — mismatch — `expected_contract_version` mandatory on every premium submission incl. the initial one — `routes/premiums.py:49`
- §3.2 (Premium) — revise — mismatch — same OCC-on-initial-premium fix in §3.2 prose — `routes/premiums.py:49`
- §2.10 — insert — ambiguity — `/_clock/set_current_utc` response shape `{ "current_utc": <iso> }`; roll returns updated contract — `routes/clock_routes.py:32,54`
- §3.1 (schedule) — revise — mismatch — `surrender_charge_schedule` per-row `contract_year` accepts any non-negative integer (incl. 0); schedule keyed by array position — `routes/products.py:49`
- §3.1 (retire) — insert — ambiguity — retiring an already-`RETIRED` product and opening a contract against a `RETIRED` product each → `ERR_INVALID_STATE` (409) — `routes/products.py:143`, `routes/contracts.py:34`
- §3.2 (is_initial) — revise — mismatch — `is_initial` keyed on prior existence of any premium (incl. REJECTED), not contract status; submission not gated on contract status apart from freeze check — `routes/premiums.py:59`
- §3.3 (crediting kind) — insert — ambiguity — source segment/allocation belonging to a different contract → `ERR_CREDITING_KIND_MISMATCH` — `routes/crediting_events.py:96,154`
- §3.3 (credit period) — insert — ambiguity — credit-period window/overlap/touch checks evaluated before segment-`OPEN` state check — `routes/crediting_events.py:109-140`
- §3.4 (anniversary roll) — insert — ambiguity — roll against non-`ACTIVE` contract → `ERR_INVALID_STATE` (409) — `routes/clock_routes.py:44`
- §3.6 (projection) — insert — ambiguity — response field names `projected_maturity_value_cents`, `settled_base_cents` (always excludes pending), `years_projected` — `routes/contracts.py:99-103`
- §3.8 (begin-payout) — insert — ambiguity — annuitization-not-`ELECTED`, contract-not-`ACTIVE`, zero/negative accumulation each → `ERR_INVALID_STATE` (409) — `routes/annuitizations.py:134-141`
- §3.8 (haircut) — insert — ambiguity — `period_certain_years` not in {10,15,20} takes haircut 100 (no haircut) — `routes/annuitizations.py:149`
- §3.9 (death-claim filing) — insert — ambiguity — non-`ACTIVE` contract and already-open/funded claim both → `ERR_INVALID_STATE`; state and existing-claim checks precede the future-date check (impl deviates from §2.9's generic 422-before-409 order) — `routes/death_claims.py:58-67`

Confirmed via test suite (test_09 self-NOTE, test_04 touch-on-CREDITED, test_07/test_03 projection asserts, fixtures with `contract_year: 0`) that these are genuine impl behaviors (tests used as auxiliary cross-reference only). Deliberately did NOT add exchange direction-vs-field prose (descriptive, not a contradicted validation rule — would be gold-plating).
