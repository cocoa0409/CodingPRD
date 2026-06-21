# Worklog — task_0181_commercial_general_liability

## Step 1: Create Task Directory — 2026-06-06T04:31:00.000Z

Created `tasks/task_0181_commercial_general_liability/` and `tasks/task_0181_commercial_general_liability/workspace/`. Output directory supplied verbatim by the invoker (no tasks/ scan, to avoid concurrent ID collision).

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-06T04:57:43.000Z

All three scaffold artifacts are complete and pass `scaffold_lint.py` cleanly.

Generated the **Expert**-difficulty scaffold for **task_0181_commercial_general_liability** (CGL administration platform). All three files written and lint-clean.

**Complexity profile:** primary archetype *ledger reconciliation* (estimated-vs-audited premium on identical exposure) + secondary *compliance/audit* (COI / additional-insured / retroactive-date gating); flat topology; compound state-machine shape; peer_roles; immediate consistency.

**Entities (11):** Insurer, Insured, CertificateHolder, Policy (hub — coverage_trigger/retro_date, dual aggregate buckets, computed posture), AdditionalInsuredEndorsement, CertificateOfInsurance, Claim, ClaimTransaction (append-only event, `common_fields:false`), PremiumAudit, ExposureRecord, LossRun.

**State machines (5):** Policy `DRAFT→BOUND→IN_FORCE→EXPIRED→AUDIT_CLOSED` (+CANCELLED); Claim with reopen cycle (`CLOSED→REOPENED→RESERVED`) and DENY release; PremiumAudit with revision cycle (`COMPLETED→DISPUTED→IN_PROGRESS→COMPLETED`) and WAIVED/FINALIZED auto-branch; AdditionalInsuredEndorsement (`ACTIVE→SUPERSEDED/VOID`); CertificateOfInsurance (`DRAFT→ISSUED→REVOKED/EXPIRED`).

**Counts:** 7 calculations (estimated_premium, audited_premium, coverage_test, claim_incurred, aggregate_erosion, policy_posture, loss_run_snapshot — dual-variant on premium and coverage trigger), 15 validations, 47 endpoints, 28 errors, 5 roles (InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor, entity-backed CertificateHolder), 2 concurrency rules (OCC on Policy.version for claim-transaction posting and audit finalize).

**Design files:** SCAFFOLD_DIFFICULTY_DESIGN.yaml — 9 rule_ids × 2 = **18 instances** (all formula-derived asserts pre-computed as literals, e.g. premium floor-then-multiply 300000, per-occurrence-then-aggregate erosion 100000000, posture impairment at exactly 25%, waiver at 49800≤50000). SCAFFOLD_CORNER_DESIGN.yaml — **40 active instances + 4 excluded_because stubs** spanning entities/state_machines/calculations/validations/endpoints/rbac/cross-cutting/consistency.

**Verification:** `scaffold_lint.py` final verdict — `clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (458 calls scanned). Enum closure verified (all status values produced by transitions), no forbidden concurrency vocabulary, no `id` in business decisions, neither design key leaks into SCAFFOLD.yaml. The hard constraint was honored — no sibling task directories were read.

Files: SCAFFOLD.yaml (1328 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1073 lines), SCAFFOLD_CORNER_DESIGN.yaml (1638 lines).

## Step 3: Copy Shared Files — 2026-06-06T04:58:03.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T05:03:09.000Z

PRD generation complete. Output: `workspace/PRD.md` (301 lines). Design indices (DIFFICULTY/CORNER) were withheld and not opened.

**Major sections:**
- **§1 Introduction** — CGL platform framing (multi-carrier tenancy, estimated-vs-audited premium reconciliation, aggregate-limit erosion, occurrence vs claims-made trigger, OCC motivation).
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (5 roles, `X-User-ID`/`X-User-Role`, opaque vs entity-backed identity), 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties (ClaimTransaction `common_fields:false` exception), 2.5 Insurer Business Clock, 2.6 Hierarchical Consistency & Cascades, 2.7 Aggregate Erosion & Posture, 2.8 OCC on Policy version (both write paths), 2.9 Monetary Precision & truncate-then-multiply rating, 2.10 Reference Integrity & left-to-right path validation, 2.11 Validation Ordering (priority chain).
- **§3 Business Logic** — 9 subsections by lifecycle: carrier setup, policy draft/bind, activate/expire/cancel, endorsements & certificates, claims & coverage trigger test, transactions/incurred/erosion, close/deny/reopen, premium audits & reconciliation, loss run snapshots.
- **§4 Endpoint Definitions** — 48 endpoints.
- **§5 Error Code Catalogue** — 28 error codes.

**Hard Contracts:** Field coverage PASS (65/65 entity fields, 2/2 request bodies, 5/5 query params). Rule coverage PASS (15/15 validations, 2/2 OCC rejections, all state transitions, 7/7 calculations, sibling-branch symmetry preserved). Path purity PASS (363 backtick tokens scanned, 0 path/method tokens in §3). §2.2 verbatim anchors present.

## Step 5: Generate Unit Tests — 2026-06-06T05:18:55.000Z

Generated complete test infrastructure for task_0181 (Commercial General Liability — Expert).

**Test files: 6** (plus `conftest.py`), in `test_suite/`:
- `test_01_policy_lifecycle.py` (19), `test_02_claims_coverage_and_transactions.py` (15), `test_03_aggregate_erosion_posture.py` (12), `test_04_endorsements_certificates.py` (9), `test_05_premium_audit.py` (10), `test_06_concurrency_rbac_and_listing.py` (9).

**Total tests: 74**, all collecting cleanly, each carrying exactly one `Design:` tag resolving to a real instance.

**Queue split:**
- **Queue A (Difficulty): 34 tests** — all 17 translated instances covered by ≥2 tests each.
- **Queue B (Corner): 40 tests** — all 40 non-stub instances covered by ≥1 test each.

**Instances skipped: 1**
- `Difficulty/priority_pair_validation_conflict/ai_endorsement_missing_beats_policy_exhausted_on_coi_issue` — SKIPPED (validation-priority Silence / unique-derivability failure). Scaffold claims `ERR_AI_ENDORSEMENT_MISSING` (priority 11) pre-empts `ERR_POLICY_EXHAUSTED` (priority 12), but PRD §3.4 lists gating checks in the opposite order with no prose committing to AI-missing firing first. A faithful PRD-only reader could return either error. The sibling instance (`forbidden_role_beats_invalid_state_on_audit_dispute`) is kept, since §2.11 states role authorization precedes the state gate.

**Excluded stubs (queue B, correctly NOT translated):** all 4 `excluded_because:` stubs verified — cross-references resolve to real Difficulty instances, none emitted as tests.

**test_helpers/ files written (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

**Key fidelity notes:** ClaimTransaction modeled with `common_fields: false` (only `id`+`created_at`; assertion rejects `updated_at`/`version`). CertificateHolder is sole `entity_backed` role with `make_certificate_holder_headers(holder_id)` builder. All 28 error IDs registered. 99 quoted PRD citations grep-verified verbatim. No skip/xfail markers.

## Step 6: Generate Implementation — 2026-06-06T05:18:55.000Z

Implementation complete.

**Files under `workspace/implementation/`:** `start.sh` (executable launcher), `requirements.txt` (`flask==3.0.3`), `app.py` (app factory, error handlers, reads `$PORT`, binds `0.0.0.0` foreground), `db.py` (in-memory `Store` — 11 dicts keyed by id, UUID + real-clock helpers, monotonic seq for creation ordering), `errors.py` (full §5 catalogue), `response.py` (envelope, `req_`-prefixed request id, ISO-8601 UTC ms), `common.py` (auth `X-User-ID`/`X-User-Role`, RBAC, common-field attach/touch, pagination), `serialize.py` (per-entity projection; ClaimTransaction omits `updated_at`/`version`), `engine.py` (premium rating truncate-then-multiply floor-at-min, claim incurred, aggregate erosion waterfall per-occurrence-before-aggregate, posture EXHAUSTED/IMPAIRED at ≤25%/HEALTHY), `routes.py` (all 46 endpoints, state machines, cascades, OCC, CertificateHolder read scoping).

**Framework / launch:** Python 3 + Flask, single-process `app.run(host="0.0.0.0", port=$PORT, threaded=True)`. `start.sh` does `cd "$(dirname "$0")"`, guards pip install behind `if ! python3 -c "import flask"`, then `exec python3 app.py`.

**Confirmed:** `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`. Storage in-memory only — restart wipes all state. No entity seeding at boot.

**Self-verification:** Booted via `start.sh`, ran ~70 endpoint assertions covering full lifecycle (auth/RBAC, envelope, policy bind/activate/cancel, estimated-premium math 1,500,000→750,000, both coverage triggers, aggregate erosion across GENERAL/PRODUCTS buckets, posture IMPAIRED-at-25%/EXHAUSTED, per-occurrence cap, OCC 412 on transactions + audit finalize, clock-driven expiry cascade, audit waive-vs-finalize with net-adjustment, deny releasing erosion, cross-insurer FK 422, 404, invalid-amount 422, pagination meta, CertificateHolder entity-backed read scoping). All passed. Note: denying a PAID claim returns `ERR_PAID_CLAIM_CANNOT_DENY` (per §3.7) rather than `ERR_INVALID_STATE`.

## Step 7: Run Tests and Iterate — 2026-06-06T05:26:24.000Z

Done. All 8 parallel rounds are green.

**Iterations run:** 2 (1 diagnostic baseline + 1 verification sweep). The baseline sweep showed a consistent (non-flaky) 71/74 in all 8 rounds — 3 failing tests, identical across every round.

**Tests deleted (1):**
- `test_create_policy_missing_coverage_trigger_rejected` (test_suite/test_01_policy_lifecycle.py) — UNIQUE-DERIVABILITY failure (required-field silence). Drove from Corner instance `Corner/entities/create_policy_missing_required_field_rejected`. PRD §3.2 lists `coverage_trigger` among the fields the Underwriter *supplies* at draft, but states no rule rejecting a missing field at create time, and §5 has no generic missing-field error. A PRD-faithful implementer may equally (i) reject at draft with a 4XX, or (ii) accept the `DRAFT` with `coverage_trigger=null` and defer validation to bind, where §3.2 explicitly branches on the trigger value. Both readings faithful → not uniquely determined. Deleted.

**Fixes applied to test_helpers/ (1):**
- `fixtures.py` → `setup_completed_audit`: re-fetch the policy via `GET /policies/{id}` before returning. The fixture previously returned the stale `DRAFT` snapshot from `create_draft_policy` (with `estimated_premium_cents=None`), so the two reconciliation tests (`test_audited_premium_and_net_adjustment_reconcile`, `test_estimated_and_audited_share_rating_on_different_exposures`) asserted `policy["estimated_premium_cents"] == 300000` against `None`. Implementation was correct — bind computes `300000` and `GET` returns it; the fixture handed back the pre-bind object. Cause of both `assert None == 300000` failures.

**Fixes applied to implementation/:** None. The implementation was PRD-faithful throughout; the two audit failures were a test-helper staleness bug and the third was a non-derivable assertion.

**Final state:** 8/8 parallel rounds pass at 73/73. Scratch `results.*.json` removed.

## Step 8: Finalize PRD — 2026-06-06T05:28:50.000Z

Produced `workspace/PRD_FINALIZED.md` (301 lines; PRD.md also 301 — one line revised in place, 0% line-count delta).

**Changes (1):**
- §3.2 — revise (in-place insert) — Pinned that draft policy creation performs no required-field/value validation on the supplied rating and coverage fields beyond `insurer_id`/`insured_id` FK resolution and `policy_number` uniqueness: an omitted field is stored as null and all trigger-dependent and structural checks (including those reading `coverage_trigger`) are deferred to bind. — implementation/routes.py:219-255 (`create_policy`, all fields stored via `body.get(...)`) vs routes.py:282-307 (`bind_policy`, where the trigger/structural checks live).

**Pre-edit search log (Edit 1, §3.2):**
- (a) Subject: create-time validation of Underwriter-supplied draft fields — whether a missing field (e.g. `coverage_trigger`) is rejected at create. Drives the Step 7 deletion of `test_create_policy_missing_coverage_trigger_rejected`.
- (b) Impl paths enumerated: `create_policy` (routes.py:219-255, only FK + policy_number uniqueness validated; all other fields `body.get(...)`→null); `bind_policy` (routes.py:282-319, all trigger-dependent + structural checks live here); grep of `routes.py` for `required|is None|missing|ERR_VALIDATION` (no generic missing-field gate at any create endpoint); `common.py get_body`/`attach_common` (no presence enforcement).
- (c) Wording adjustment: carved out the two create-time checks that DO run (FK resolution per §2.10, policy_number uniqueness) so the sentence does not falsely claim "no validation at all"; scoped "these supplied fields" to the §3.2 draft list and "enforced only at bind" to trigger-dependent/structural checks.

**No PRD edit for items 2 & 3:** item 2 (fixtures.py `setup_completed_audit` stale-snapshot re-fetch) is a pure test-helper bug — bind→`estimated_premium_cents`→GET is already fully determined by §3.2; item 3 reports no implementation fixes. Neither is a PRD silence or mismatch.

## Step 9: Complete PRD — 2026-06-06T05:34:18.000Z

Produced `workspace/PRD_COMPLETED.md` from full PRD-vs-implementation scan. Source `PRD_FINALIZED.md` = 301 lines / 43953 chars → `PRD_COMPLETED.md` = 301 lines / 46356 chars. Char delta = **+2403**. All in-paragraph inserts/revisions; no new sections, no line-count change.

**Counts:** ambiguity-pins = 5, mismatch-revisions = 0. (No outright impl-vs-PRD contradictions; every change pins a behavior PRD left open to multiple readings.)

**Per-change:**
- **§2.1 (RBAC / CertificateHolder)** — insert — ambiguity — Holder ownership check applied *only* as a list-endpoint filter and *only* to resource kinds carrying `certificate_holder_id` (endorsements, certificates); kinds without it (loss runs) returned unfiltered; single-resource GETs not ownership-gated. — `routes.py:67-69` (`_list_response`), `routes.py:52-61` (`_holder_can_read`).
- **§2.3 (Pagination)** — insert — ambiguity — Out-of-range/unparseable `limit`/`offset` silently coerced (clamp to 1/100, neg offset→0, non-integer→default); `meta` echoes effective values; created-order tie-break by internal monotonic creation sequence. — `common.py:81-104`, `db.py:27-29`.
- **§2.4 (Common resource properties)** — revise — ambiguity — `version` initial value = `1`; `updated_at` equals `created_at` at creation. — `common.py:43-49`.
- **§3.6 (Claim transactions)** — insert — ambiguity — Within-post check order (state gate → opening-only IN_FORCE + coverage trigger → amount validity → release/recovery overrun → OCC last); JSON boolean rejected as non-integer amount; coverage-trigger errors outrank `ERR_INVALID_AMOUNT` on opening reserve. — `routes.py:616-662`, `routes.py:641`.
- **§3.8 (Audit finalize)** — insert — ambiguity — WAIVED branch also mutates policy (version/updated_at advance) and performs *no* `expected_policy_version` check; *only* FINALIZED branch runs OCC, comparing version before mutating. — `routes.py:918-949`.

No changes needed for the policy/claim/endorsement/certificate/exposure/loss-run lifecycles, rating/erosion/posture formulas, error catalogue, cascade rules, or endpoint/role table — PRD already pins those uniquely and they match impl.

---

## Pipeline complete

All 9 steps finished. Final test state: **73/73 passing across 8/8 parallel stability rounds** under `prd-bench-local-run --isolation per-test-server`. Deliverables present: SCAFFOLD.yaml (+DIFFICULTY/CORNER design indices), workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/, test_suite/ (73 tests), workspace/implementation/ (Python+Flask, in-memory).
