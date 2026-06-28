# Worklog — task_0609_valuables_jewelry_insurance

## Step 1: Create task directory — 2026-06-21T17:21:53.222Z

Created `tasks/task_0609_valuables_jewelry_insurance/` with `workspace/` subdirectory. Pre-allocated path used verbatim (no auto-indexing). Verified `INSTRUCTION.md` present at project root and all `prd-bench-*` skills available under `skills/`.

## Step 2: Generate scaffold (Expert band) — 2026-06-21T17:48:00.000Z

All asserts hold exactly. The scaffold is complete, internally consistent, and lint-clean.

## Summary

Generated all three scaffold artifacts for **task_0609_valuables_jewelry_insurance** at the **Expert** difficulty band, lint-clean, in `/home/ubuntu/github/CodingPRD/tasks/task_0609_valuables_jewelry_insurance/`.

**Domain design** — Valuables & Jewelry Insurance (Jewelers Mutual style). Primary archetype: ledger reconciliation + pricing engine; topology hybrid (Policy aggregate root + flat RepairShop/RiskZone/Policyholder peers); state-machine shape cyclic; role model peer_roles; layers: dual-variant calc, cascading side-effects, rate/threshold triggers, optimistic concurrency.

**SCAFFOLD.yaml counts:**
- **Entities: 10** — Policyholder, RiskZone, RepairShop, Policy, ScheduledItem, Appraisal, Endorsement, Claim, RepairOrder, PremiumPayment
- **State machines: 6** — Policy (parallel dimensions: coverage_status × billing_status), ScheduledItem, Endorsement, Claim (cyclic UNDER_REVIEW↔INFO_REQUESTED), RepairOrder (branching fork-join REPAIRED vs DEEMED_TOTAL_LOSS), Appraisal
- **Concurrency rules: 2** (OCC) — endorsement-apply-stale-policy (Policy.version), claim-approve-stale-claim (Claim.version)
- **Calculations: 6** with 4 variants — `claim_settlement` (AGREED_VALUE vs REPLACEMENT_COST), `item_revaluation` (SIMPLE vs COMPOUND inflation guard), `item_annual_premium` (tiered multi-factor, mode a), `policy_annual_premium` (round-per-item-then-sum pinned, mode b), `deductible_resolution` + thresholds, `endorsement_premium_delta` (proration)
- **Validations: 21** (priority-ordered) · **Endpoints: 44** · **Errors: 21** · **Roles: 5** (Underwriter, ClaimsAdjuster, Appraiser, Policyholder[entity_backed], RepairShop[entity_backed])

**§1.8 difficulty design:** 9 rules × 2 = **18 instances**, every rule's differentiation clause satisfied. All formula-derived asserts are pre-computed literals (e.g., 1,050,000 vs 850,000 settlement; 1,150,000 vs 1,157,625 revaluation; 5921 round-then-sum premium).

**§1.9 corner design:** **39 instances** (31 with executable test_recipes + 8 `excluded_because` stubs) across all 9 taxonomy sections, including both OCC stale-version negative tests, required-field/not-found/computed/system-field, invalid-from rejections, RBAC denials with entity_backed ownership, and consistency-model claims.

**Lint:** `VERDICT: clean lint` — all 430 §1.8/§1.9 calls conform to §1.5; all 11 §1.1 FKs have reverse-reachability GETs.

Key design decision: `api_prefix` is empty (`""`) because the domain has multiple top-level collections (flat topology); billing was modeled so PAST_DUE is entered only by explicit payment reversal (never automatic on clock advance).

## Step 3: Copy shared files — 2026-06-21T17:48:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-21T17:53:00.000Z

Generated `workspace/PRD.md` for the **valuables-jewelry-insurance** Expert-band domain.

**Structure:** 5 top-level sections, 295 lines.
- §2 Global Specs: 10 subsections (RBAC, fixed response envelope, pagination, common properties, precision/rounding, logical clock, hierarchical consistency, nested retrieval, OCC, validation ordering)
- §3 Business Logic: 14 subsections (catalogs → quoting → binding → pricing → revaluation → billing → lapse/reinstatement → cancellation → endorsements → proration → claims adjudication → settlement calc → settle/close → repair path)
- §4: 44-endpoint table — matches scaffold exactly
- §5: 21-error catalogue

**Hard Contract reports:** Contract 1 (Field-Name Coverage) PASS — 60/60 required fields present. Contract 2 (Rule Coverage) PASS — 21 validations, 2 OCC rules (ERR_STALE_VERSION + HTTP 412), all state machines + 6 calculations expressed with constants embedded. Contract 3 (§3 Path Purity) PASS — 0 path/method tokens in §3 prose.

**Notable decisions:** RiskZone is the lone `common_fields: false` entity (only id+created_at). Two floor-not-round points (in-network deductible halving, completed-policy-year count) flagged. Logical-clock default `2026-01-01T00:00:00Z`; three time-driven cascades anchored. Both withheld SCAFFOLD_*_DESIGN.yaml files were NOT read.

## Step 5: Generate unit tests — 2026-06-21T18:05:00.000Z

Test infrastructure generation complete for `task_0609_valuables_jewelry_insurance`.

**Stage 1 — `test_helpers/` (9 modules):** `types.py` (entity TypedDicts with correct `common_fields` branching — RiskZone carries only `id`/`created_at`, no `updated_at`/`version`), `api_client.py` (one method per PRD endpoint), `api_errors.py` (21 error IDs + HTTP-status map), `assertions.py`, `factories.py` (input-only), `constants.py`, `test_users.py` (opaque vs entity-backed roles), `fixtures.py` (composite setup chains), barrel `__init__.py`.

**Stage 2 — `test_suite/` (8 test files + conftest, 65 tests):**
- **Queue A (Difficulty): 34 tests.** 17 of 18 instances covered with ≥2 tests each.
- **Queue B (Corner): 31 tests.** All 31 non-stub instances covered with ≥1 test each.

All 65 tests collect; every Design: tag verbatim; no skip/xfail; no scaffold leakage.

**Instances skipped under the PRD-first filter (1):**
- **`Difficulty/priority_pair_validation_conflict/bind_appraisal_required_beats_named_peril_perils`** — SKIPPED (error-precedence silence). Scaffold asserts `ERR_APPRAISAL_REQUIRED` pre-empts `ERR_NAMED_PERIL_REQUIRES_PERILS` (priority 8<9), but PRD §3.3 lists named-peril BEFORE appraisal in prose and states no numeric priority. Not uniquely derivable. Gap left as gap.

## Step 6: Generate implementation — 2026-06-21T18:05:00.000Z

Implementation complete in `workspace/implementation/`.

**Module layout:** `start.sh` (foreground, binds 0.0.0.0:$PORT default 10000), `app.py` (Flask + blueprints + error handlers), `db.py` (in-memory dict store + version helpers), `clock.py`/`dateutil_min.py` (logical clock default `2026-01-01T00:00:00Z`), `reconcile.py` (time-driven cascades), `calc.py` (all calculations, Decimal/ROUND_HALF_UP + explicit floor on the two PRD spots), `errors.py`/`response.py`/`serializers.py`/`validators.py`/`middleware.py`/`lookups.py`, `routes/` + `services/`.

**Endpoints:** 44 handlers covering full PRD §4 surface. **Storage:** in-memory dicts keyed by id, wiped on every boot; no seeding, no disk persistence.

**Notable decisions:** PRD-over-scaffold bind order (no-items → named-peril → appraisal, contradicting scaffold priorities 8/9/10 — PRD wins, matching the Step-5 skip). In-network deductible halving at repair-order assignment. OCC int-coerces version inputs. Reinstatement window anchored at `past_due_since`. Real wall-clock for created_at/updated_at; logical clock for domain time. Self-verified worked examples (premium 3947, in-network settlement 275000, SIMPLE 1200000 vs COMPOUND 1210000, replacement-cost 950000).

## Step 7: Run tests and iterate — 2026-06-21T19:00:00.000Z

Recovered/finalized by orchestrator after the original `claude -p` print session ended mid–Step 7. The original Step-7 sweep ran while all 6 sibling pipelines were saturating the host (8×6 concurrent per-test-server reboots), which starved server boots and produced a spurious all-failing sweep ("API server could not be restarted" on setup, 0/65). The server boots cleanly in ~1s in isolation; no implementation or test defect was involved.

Re-ran the canonical 8-round parallel stability sweep on a quiet host:
- **65/65 passing in every one of the 8 rounds** (results.{1..8}.json), 0 failed, 0 errors, 0 skipped per round.

Iterations run: 0 real fix-iterations. Tests deleted: 0. test_helpers/ fixes: 0. test_suite/ fixes: 0. implementation/ fixes: 0. PRD already determined every behavior the implementation exhibits at the test-exercised sites → Step 8 (PRD_FINALIZED) skipped per the skip condition. Step 9 (PRD_COMPLETED) runs next.
