# Worklog — task_0200_aml_kyc_sanctions_screening

## Step 1: Create task directory — 2026-06-06T16:28:49.000Z

Task directory `tasks/task_0200_aml_kyc_sanctions_screening` was pre-allocated (Step 1 auto-scan skipped per orchestration instruction). Verified `tasks/task_0200_aml_kyc_sanctions_screening/workspace/` exists and is empty. Scaffold to be generated at Expert difficulty (§0.4 Expert calibration band).

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-06T16:59:00.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` with `VERDICT: clean lint`.

Generated the Expert-difficulty scaffold for **AML/KYC & Sanctions Screening** at `tasks/task_0200_aml_kyc_sanctions_screening/`:
- `SCAFFOLD.yaml` (§1.0–§1.7, 1945 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key, 936 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key, 1914 lines)

**Complexity profile:** primary archetype `compliance_audit` + secondary `workflow_orchestration`; `graph` topology; `cyclic` state-machine shape; `segregation_of_duties` role model (4-eyes); `immediate` consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers.

**Counts (Expert band):**
- **12 entities** (Customer, BeneficialOwner, RiskAssessment, ScreeningHit, Account, Transaction, Alert, Case, Filing, LookbackReview, LookbackReviewItem, AuditEvent)
- **7 state machines** — cyclic (Customer APPROVED↔EDD_REQUIRED, ScreeningHit ESCALATED↔PENDING), fork-join branching (Case → SAR/CTR/CLOSE then re-converge on FILED), parallel dimensions (Account `kyc_status` × `monitoring_status`), compound (LookbackReview derived from items)
- **8 calculations, 4 variants** — `risk_scoring` (provisional/final band-flip), `transaction_monitoring` (instantaneous/cumulative-window CTR), plus `edd_gate`, `alert_severity`, `case_priority`, `filing_deadline`, `review_cadence`, `lookback_window_membership`
- **26 validations** (priority-ordered), **51 endpoints** (28 write + 23 read/FK-reverse GETs + 1 `/_clock` test-driving), **26 error codes**, **5 RBAC roles** (ComplianceOfficer, Analyst, QualityReviewer, SystemFeed, PlatformAdmin), **2 OCC concurrency rules**
- **Difficulty design (§1.8):** 9 rule_ids × 2 instances = 18 instances
- **Corner design (§1.9):** 60 instances total = 56 active + 4 `excluded_because` stubs, all 9 sections

**Verification:** all calc formulas computed in Python before writing literals; PROHIBITED-band reachability fixed (threshold 84); FINAL-variant trigger corrected to CONFIRMED-derogatory; lint passes clean (370 calls scanned, 0 violations); design keys correctly isolated to their own files.

## Step 3: Copy shared files — 2026-06-06T17:01:17.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0200_aml_kyc_sanctions_screening/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T17:09:38.000Z

Generated the PRD at `workspace/PRD.md` (318 lines, 51899 bytes).

**Sections covered:**
- §1 Introduction — AML/KYC regulatory domain, cyclic CDD coupling, segregation-of-duties/OCC drivers.
- §2 Global Specifications — 12 subsections: RBAC (5 roles, opaque-identity prose); §2.2 verbatim response envelope; pagination; common resource properties (Transaction/AuditEvent carry only id+created_at); hierarchical consistency/cascades; nested-resource existence ordering; validation precedence; precision/integer-cents; logical clock; audit trail; OCC (expected_case_version + expected_customer_version, ERR_STALE_VERSION/412); cross-cutting sanctions/risk-posture invariant.
- §3 Business Logic — 10 subsections: cyclic CDD lifecycle, risk scoring (weighted formula + PROVISIONAL/FINAL variants), review cadence, beneficial ownership, screening-hit disposition, accounts/parallel dimensions/transaction monitoring (4 rules in fixed precedence), alert severity, case fork-join, filings/four-eyes, lookback review.
- §4 Endpoint table — 4 columns, all 51 endpoints.
- §5 Error catalogue — 2 columns, all 26 error codes.

**Hard Contracts — all PASS:** Contract 1 (Field-Name Coverage) 69 entity fields + 47 endpoint-input identifiers, 0 missing; Contract 2 (Rule Coverage) all 26 errors, both OCC rules, all 8 calculations, all transitions/orderings; Contract 3 (§3 Path Purity) 517 tokens, 0 violations.

**Confirmation:** SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were NOT read.

## Step 5: Generate unit tests — 2026-06-06T17:27:06.000Z

Generated complete test infrastructure, translating every non-stub instance from the two design indices under the PRD-first filter.

**Test files: 8** (1 conftest + 7 test modules), **92 test functions total.**

**Queue split:**
- Queue A (Difficulty): 36 tests — all 18 difficulty instances, each covered by exactly 2 tests (distinct facets, each with verbatim PRD citation).
- Queue B (Corner): 56 tests — all 56 non-stub corner instances, each covered by 1 test.

**Instances skipped under PRD-first filter: 0.** Every difficulty and non-stub corner instance had verbatim PRD coverage with unique derivability. The 3 `excluded_because` corner stubs were correctly NOT translated.

**test_helpers files (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py` (26 error IDs + HTTP status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (5 roles opaque), `fixtures.py`.

**Audit (all green):** 18/18 difficulty ≥2 tests; 56/56 corner ≥1 test; every test exactly one Design: tag (0 untagged/multi/ghost); 130 PRD citations verbatim; no skip/skipif/xfail; all files compile.

Test modules: `test_01_risk_and_alert_scoring`, `test_02_customer_lifecycle`, `test_03_screening_hits`, `test_04_transaction_monitoring`, `test_05_cases_and_filings`, `test_06_lookback_review`, `test_07_entities_and_validations`.

## Step 6: Generate implementation — 2026-06-06T17:27:06.000Z

Built complete Python + Flask implementation in `workspace/implementation/`.

**Files created (15):** `start.sh`, `requirements.txt` (flask==3.0.3), `app.py` (blueprint registration + §2.2 error envelope handler), `db.py` (12 in-memory dicts keyed by id), `clock.py` (logical clock §2.9), `response.py`, `errors.py` (26 error ids + HTTP codes), `middleware.py` (auth + RBAC 5 roles), `validation.py`, `calculations.py` (all 8 calcs), `services.py` (audit + edd-gate recompute + cascades), `routes/` (7 modules).

**Endpoints:** All 51 from PRD endpoint table (28 writes + 23 reads).

**State & storage:** In-memory only — module-level dicts keyed by UUID. No SQLite, no JSON-on-disk, no /tmp. No seeding/preload. Fresh boot starts empty.

**start.sh contract — confirmed:** reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`, guarded pip install. Boot via `bash start.sh` responded HTTP 200 within ~1s.

**Verification:** ~75 ad-hoc assertions across smoke suites covering CDD lifecycle, risk bands + PEP/media surcharge, account cascades, OCC, FINAL-variant, all 4 monitoring rules + CTR boundary, case fork-join, 4-eyes filing, lookback. All genuine checks pass; all modules compile.

**Note:** `prd_bench_local_runner` not pip-installed during generation; Step 5 tests validated via byte-compilation + static cross-reference (runner installs framework at eval time / Step 7).

## Step 7: Run tests and iterate — 2026-06-06T17:39:52.000Z

Done. All tests pass across two consecutive clean 8-round parallel sweeps.

**Iterations run:** 3 sweeps (1 baseline diagnostic + 2 confirmation). The first sweep had `flock`-style boot contention masking the picture; 4 of 8 rounds went green once the harness noise was logged separately.

**Root-cause split of the initial failures:**
- One genuine logic failure: `test_apply_rating_no_unapplied_assessment` (failed deterministically in every round that booted).
- All other non-passes were 8x-parallel boot contention: `error` "API server could not be restarted before..." (a different random victim test each round) and one `ConnectionError: BadStatusLine` (server killed mid-request). No deterministic logic defect — rounds 4/5/6/8 already proved 92/92 was reachable.

**Tests deleted:** none. (The one real failure was a test bug, not a coverage/derivability problem.)

**Fixes applied to test_suite/** (`test_05_cases_and_filings.py`, `test_apply_rating_no_unapplied_assessment`): the test exercised `ERR_NO_UNAPPLIED_ASSESSMENT` by re-applying an already-applied assessment. But PRD §2.7 (line 107) fixes precedence: for transition endpoints, `ERR_INVALID_STATE` (state-machine legality) is checked *before* business rules, and §3.1 (line 145) makes apply-rating require the customer be in `NEW`. Re-applying necessarily means the customer already left `NEW`, so the higher-precedence state check fires first and `ERR_INVALID_STATE` is the PRD-mandated outcome — the implementation was correct. This is a STEP 2 fixture/precondition bug: the setup constructed a request that can't reach the rule under test. Fixed the setup to reference a *second customer's* unapplied assessment while the target customer stays in `NEW` (state OK, version OK, FK exists), so the only check that can fail is the "matching unapplied assessment for this customer" rule → `ERR_NO_UNAPPLIED_ASSESSMENT`. The exact error_id assertion was preserved.

**Fixes applied to test_helpers/:** none.

**Fixes applied to implementation/** (`start.sh`): replaced the per-restart `python3 -c "import flask"` probe (a full interpreter spawn + Flask import on every one of the ~92 per-test reboots) with a one-time filesystem sentinel (`.deps_ok`). This roughly halves per-boot CPU work under the 8x concurrent sweep, eliminating the "could not be restarted" readiness-window timeouts. The sentinel is a dependency-resolution marker only — no entity/application state is persisted; storage remains in-memory dicts wiped by each fresh process.

**Final pass count:** 92/92 passed, 0 failed, 0 errors — identical across all 8 rounds, confirmed on two consecutive sweeps (verified results.1..8.json all passed=92 total=92 failed=0).

## Step 8: Finalize PRD — 2026-06-06T17:42:13.000Z

Step 8 ran (not skipped — Step 7 had 1 test_suite fix + 1 implementation/start.sh fix). `PRD_FINALIZED.md` was produced as a **verbatim copy** of `PRD.md`. **Zero edits** — neither Step 7 item revealed a PRD silence or PRD/impl mismatch. Confirmed byte-identical via `diff` (318 lines each, 0% delta).

**Why each <step_7_diff> item is NOT a PRD silence/mismatch:**
1. **start.sh boot-performance fix (filesystem sentinel):** subject = server boot path / dependency resolution. The `.deps_ok` sentinel replaces a per-restart `import flask` probe; it is a dependency-resolution marker only, persists no entity/application state (storage remains in-memory dicts wiped per process). Pure infrastructure, exercises no PRD-described API behavior. Not a silence/mismatch.
2. **test_suite fixture fix (`test_apply_rating_no_unapplied_assessment`):** subject = `ERR_NO_UNAPPLIED_ASSESSMENT` rule on apply-rating + precedence vs `ERR_INVALID_STATE`/`ERR_STALE_VERSION`. Enumerated `routes/customers.py:179-223` (apply_rating: role → found → ERR_INVALID_STATE if not NEW → ERR_STALE_VERSION → unapplied-assessment rule) and corrected test at `test_05_cases_and_filings.py:445-471`. PRD §3.1 already pins the rule ("matching assessment must be a RiskAssessment for this customer ... whose applied flag is still false; if none matches → ERR_NO_UNAPPLIED_ASSESSMENT") and §2.7 already fixes state-before-OCC-before-business-rule precedence. Pure fixture/precondition bug; impl was already correct; PRD already fully determines every branch. No wording adjustment needed.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-06T17:48:19.000Z

Full PRD-vs-implementation scan, starting from `PRD_FINALIZED.md`. Produced `PRD_COMPLETED.md`.

**File deltas (PRD_FINALIZED.md → PRD_COMPLETED.md):** lines 318 → 318 (all edits in-paragraph); chars 51,899 → 53,446 (+1,547).

**Counts:** 8 ambiguity-pins, 1 mismatch-revision (9 edits total).

**Per-change list:**
- §2.4 (version) — insert — ambiguity — pinned `version` initial value to 1 — db.py:69
- §2.9 (logical clock) — insert — ambiguity — pinned that the logical clock sources every server-minted `created_at`, `updated_at`, `api_request_timestamp` — clock.py:31-40 + db.py:64/75 + response.py:32
- §2.12 (gate recompute triggers) — revise — mismatch — added two missing recompute triggers: screening-hit recording (customer/UBO) and screening-hit reopen — screening.py:180-183, 311-314
- §3.1 (clear-screening) — insert — ambiguity — pinned unscreened-UBO clearance on LEGAL_ENTITY → ERR_INVALID_STATE — customers.py:247-250
- §3.5 (hit disposition) — insert — ambiguity — pinned FALSE_POSITIVE on confirmable sanctions match → ERR_INVALID_STATE — screening.py:247-251
- §3.6 (post transaction) — insert — ambiguity — pinned `posted_at` stored/returned normalized to UTC with three fractional digits — accounts.py:158, 191
- §3.7 (alert listing) — insert — ambiguity — pinned per-account alert list accepts optional `status` filter — accounts.py:226-228
- §3.8 (link alert) — insert — ambiguity — pinned linking permitted only from TRIAGE/INVESTIGATING else ERR_INVALID_STATE, after existence and before stale-version — cases.py:119-124
- §3.8 (case disposition) — insert — ambiguity — pinned three error contracts: disposition from non-INVESTIGATING → ERR_INVALID_STATE; RECOMMEND_SAR with zero linked alerts → ERR_INVALID_STATE; CLOSE_NO_ACTION by non-ComplianceOfficer → ERR_FORBIDDEN (evaluated after decision-value and state checks) — cases.py:185-191, 208-211

**Deliberate non-changes:** generic illegal-transition errors already covered by §2.7 umbrella rule (ERR_INVALID_STATE for all transition endpoints); CTR strict boundary, risk-scoring surcharge, severity/priority bands, filing deadlines, OCC all already uniquely pinned and matching impl.

---

## Pipeline complete — 2026-06-06T17:48:19.000Z

All 9 steps finished. Final state: 92/92 tests passing across 8 parallel rounds (two consecutive clean sweeps). Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/ (92 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
