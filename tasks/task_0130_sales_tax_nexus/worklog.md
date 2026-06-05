# Worklog — task_0130_sales_tax_nexus

Scenario: Sales Tax Compliance (Nexus): product taxability/category, economic-nexus threshold by state, origin/destination rate, exemption certificate, marketplace facilitator, return filing/remittance, audit trail, use tax accrual
Difficulty: Expert (Step 2 scaffold-generator only)

## Step 1: Create task directory — 2026-06-03T17:37:29.000Z

Created `tasks/task_0130_sales_tax_nexus/` and `tasks/task_0130_sales_tax_nexus/workspace/` (pre-allocated path; no index scan performed).

## Step 2: Generate scaffold (Expert) — 2026-06-03T17:59:30.000Z

All three scaffold artifacts are generated and validated for `task_0130_sales_tax_nexus`.

Generated a fresh Expert-tier Sales Tax Compliance (Nexus) scaffold purely from the scenario description and the scaffold-generator spec. Three files written: SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8), SCAFFOLD_CORNER_DESIGN.yaml (§1.9).

**Counts**
- Entities: **12** (TaxJurisdiction, ProductCategory, Seller, NexusProfile, ExemptionCertificate, MarketplaceFacilitator, Transaction, TransactionLineItem, UseTaxAccrual, TaxReturn, RemittancePayment, AuditLogEntry)
- State machines: **4** (Transaction parallel settlement×audit dimensions; ExemptionCertificate cyclic ACTIVE↔REVOKED; NexusProfile derived posture; TaxReturn fork-join with revert)
- Calculations: **6** (line_item_tax, sourcing_resolution, nexus_status, remittance_responsibility, use_tax_accrual, return_tax_due)
- Validations: **16** (priority-ordered)
- Endpoints: **48** (47 business + 1 test-driving `/_clock/set_current_utc`)
- Errors: **17**
- Roles: **5** (PlatformAdmin, Seller, TaxPreparer, TaxApprover, Auditor — segregation-of-duties)
- Concurrency rules: 1 (OCC on TaxReturn.version for remittance)

**Difficulty-design instances**: **18** (9 rules × 2). **Corner-design instances**: **39** (33 active + 6 `excluded_because` stubs).

**Design notes**
- Archetype: compliance/audit + pricing-engine; flat topology (`api_prefix: ""`) so all 17 FKs are reverse-reachable via filtered-list GETs.
- Rule 8 (temporal overlap): ExemptionCertificate half-open windows (adjacency allowed) vs TaxReturn closed windows (adjacency forbidden) — added `ERR_CERTIFICATE_OVERLAP` and `ERR_RETURN_PERIOD_OVERLAP`.
- Rule 2b rounding-order divergence pinned and verified by code: two FULL lines @ 7.95 × 0.0825 → round-then-sum **1.32** vs sum-then-round 1.31. Formula assert literals computed in Python (8250.00, 99.00, 100.32, 3.48, 0.83, 8.25).

**Linter**: `scaffold_lint.py` final verdict — **clean lint** (48 endpoints, 12 entities, 18 §1.8 + 33 §1.9 instances, 341 calls scanned; all calls conform to §1.5 and all FKs reverse-reachable). Self-checks confirmed: every grounds reference resolves, all `excluded_because` stubs cite real §1.8 instances, all instance names unique, every error code exercised by ≥1 design instance.

Files: SCAFFOLD.yaml 1470 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1221 lines, SCAFFOLD_CORNER_DESIGN.yaml 1364 lines.

## Step 3: Copy INSTRUCTION.md — 2026-06-03T17:59:50.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-03T18:04:25.000Z

PRD generated at `workspace/PRD.md` — **281 lines**, 40736 bytes. Read SCAFFOLD.yaml only; confirmed neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened.

**Major sections:** §1 Introduction; §2 Global Specs (2.1 RBAC 5 roles, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Common Properties & Versioning, 2.5 Nexus Posture & Threshold, 2.6 Sourcing/Rates/Precision round-half-up 2dp, 2.7 Audit Trail, 2.8 OCC on Remittance, 2.9 Validation Ordering); §3 Business Logic (11 subsections: config; nexus open+register; transaction+line-item; settlement sourcing/taxability/round-then-sum; remittance responsibility & nexus accrual/de-accrual; audit dimension; exemption certs half-open overlap + lazy expiry; use-tax accrual; return prepare/accept/reject/reopen sweep + tax_due + SoD + nexus precondition; file/remit closed-interval overlap + OCC + amount match; test clock); §4 Endpoint table (4-col, all 48); §5 Error catalogue (2-col, all 17).

**Hard Contracts:** Contract 1 Field-Name Coverage 55/55, all query params, 0 missing. Contract 2 Rule Coverage — 14 transitions, 5 calculations, OCC rule (`expected_tax_return_version` + `ERR_STALE_VERSION`/412), all 17 error IDs in narrative + table. Contract 3 §3 Path Purity — 355 tokens scanned, 0 path tokens / 0 bare methods / 0 method+path combos. All PASS.

## Step 5: Generate unit tests — 2026-06-03T18:19:58.000Z

Everything compiles and the coverage is complete. Here is the final report.

Generated complete test infrastructure for `task_0130_sales_tax_nexus` from the two design indices only (no freelance walking of SCAFFOLD.yaml).

### Output

**`test_helpers/` (9 files):**
`__init__.py` (barrel export), `types.py` (11 entity TypedDicts + 11 enums; line items and audit entries correctly carry only `id`/`created_at`), `api_client.py` (one method per endpoint incl. `set_clock`), `api_errors.py` (17 error IDs + HTTP status map registered with the framework), `assertions.py` (per-entity assertions + append-only/full common-field split), `factories.py` (input-fields-only payload factories), `constants.py` (canonical CA/TX/NY jurisdictions + thresholds), `test_users.py` (opaque-role constants + `make_seller_headers` per-instance builder for the entity-backed Seller role), `fixtures.py` (composite chains: reference data → seller/profile → transactions/line-items → settle/accrue → register → certificates → use-tax → full return lifecycle incl. `setup_filed_return_ca`).

**`test_suite/` (7 test files + conftest.py):** 65 test functions.

### Coverage

- **Queue A (Difficulty):** 16 of 18 instances → 32 tests (≥2 per instance, enforced).
- **Queue B (Corner):** all 33 non-stub instances → 33 tests (≥1 each). The 6 `excluded_because:` stubs were not translated; their cross-references were verified to resolve to real difficulty instances.
- Every test docstring carries exactly one `Design:` tag and ≥1 verbatim PRD citation. Automated audit confirms: 76/76 citations literal-grep-verbatim against PRD.md (backticks included), zero untagged/dual-tagged tests, zero skip/xfail markers, zero scaffold-section leakage in emitted code.

### Skipped instances (2, both Queue A)

Both from **Rule 5 `priority_pair_validation_conflict`**, skipped under the **validation-priority Silence pattern** (PRD does not uniquely-derive the error precedence):
- `state_beats_segregation_on_accept_nondraft` — PRD §2.9 lumps state checks and segregation into one unordered "state and business-rule checks" final bucket; two PRD-only implementers could return either `ERR_INVALID_STATE` or `ERR_SEGREGATION_OF_DUTIES`.
- `segregation_beats_nexus_on_accept_draft` — same bucket; "further requires" describes logical layering, not a committed error-reporting order, so segregation-vs-nexus precedence is not uniquely derivable.

Consequence: the corner stub `segregation_of_duties_same_user_already_covered` delegated to the skipped 5b, so a same-user-segregation single-failure assertion is a genuine PRD gap — left as a gap per the design-index-only contract (no freelance test invented).

All files byte-compile and the suite collects cleanly under the framework (`prd_bench_local_runner.testing`).

## Step 6: Generate implementation — 2026-06-03T18:19:58.000Z

Implementation complete and verified.

Built a complete Python + Flask implementation of the Sales Tax Nexus API at `workspace/implementation/`.

### Files produced
- `start.sh` — foreground launcher (executable)
- `requirements.txt` — `flask==3.0.3`
- `app.py` — entry point: blueprint registration, envelope error handlers, port binding + bind-retry loop
- `db.py` — in-memory dict store, UUID/timestamp/request-id helpers, test-driving logical clock
- `errors.py` — `APIError` + the 17 error IDs with their HTTP codes
- `response.py` — success/array/error envelope helpers (`meta`/`response_type`/`data`)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth + RBAC `@require(...)` decorator
- `routes/` — `config.py`, `nexus_routes.py`, `certificates.py`, `transactions.py`, `use_tax.py`, `returns.py`, `audit.py`
- `services/` — `common.py` (validation/pagination/audit), `serializers.py`, `nexus.py` (posture recompute), `settlement.py` (sourcing + round-then-sum tax + accrual)

### Framework / storage
Flask 3.0.3, all state in module-level Python dicts keyed by UUID. No SQLite, no JSON dump, no /tmp cache — a fresh process wipes everything. No seeding/preloading at startup.

### Endpoint count
**48 route handlers**, matching the PRD §4 endpoint table 1:1.

### Boot/runtime contract confirmed
`start.sh` reads `$PORT` (default 10000), binds `0.0.0.0:$PORT` in the foreground via `exec python3 app.py`, guards the pip install behind an `import flask` sentinel, and `app.py` runs a same-port bind-retry loop before `app.run`. Verified by launching through `start.sh`: server HTTP-ready in ~0.5s, created seller disappeared after relaunch (state wiped 1→0), rapid same-port relaunch succeeded via bind-retry.

### Behavior verified
79 smoke-test assertions across three suites passed (0 failures), covering combined-rate computation, duplicate/uniqueness conflicts, ORIGIN vs DESTINATION sourcing, round-then-sum per-line tax, EXEMPT category and certificate-based exemption (half-open overlap rejection + adjacency allowance), marketplace-facilitator MARKETPLACE responsibility (tax computed but no nexus accrual), nexus accrual/de-accrual via settle/void, both sales and count threshold tests, sticky REGISTERED posture surviving a void, segregation-of-duties control, nexus-registration precondition, transaction-locking after sweep, return tax_due, OCC stale-version + amount-mismatch on remittance, validation priority ordering, RBAC/audit-log visibility.

## Step 7: Test & fix loop — 2026-06-03T18:27:51.000Z

Two consecutive clean 8-round sweeps. Done.

**Iterations run:** 2 (initial diagnostic sweep at 60/65, then one fix batch reaching 65/65; confirmed with a second 8-round sweep).

**Root cause:** All 5 failures were deterministic (failed in all 8 rounds, not flaky) and traced to one test-helper bug plus two redundant test-suite calls — the implementation was fully PRD-faithful and was not touched.

The `setup_registered_seller_ca` fixture settled its large threshold-crossing transaction (100000.00) at the same clock instant (`2026-02-15`) that the downstream tests put inside their return period (`2026-02-01`..`2026-03-01`). Per PRD §3.9, the acceptance sweep "gathers ... every transaction ... whose `settlement_status` is `SETTLED` ... whose `remittance_responsibility` is `SELLER`, and whose `created_at` falls in the period," so a faithful implementation correctly folds that transaction's `tax_collected` (8250.00) into `tax_due`. The tests expected only the small in-period sale/use-tax, so their `tax_due` sanity assertions tripped (8250.83 vs 0.83; 8350.32 vs 100.32). This is a test-precondition bug, not an implementation bug.

**Tests deleted:** none. Every failing assertion was PRD-covered and uniquely derivable; the failures were precondition/setup bugs.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_registered_seller_ca`: now settles the threshold-crossing transaction at a pre-period clock (`threshold_clock="2026-01-15"`, before any return period these tests file), then advances the clock to `working_clock="2026-02-15"`. Nexus accumulators are persistent/period-independent, so the profile still registers, but the large transaction is no longer swept into the February return — making the fixture consistent with PRD §3.9's half-open period sweep.

**Fixes applied to `test_suite/`:**
- `test_05_returns_and_remittance.py` — removed two redundant `fx.create_category(ca["id"], "TANGIBLE", "FULL")` calls in `test_transaction_void_blocked_when_swept_into_return` and `test_unswept_settled_transaction_can_still_be_voided`. `setup_registered_seller_ca` already creates that category, so the second call hit the PRD §126 (jurisdiction_id, category_code) uniqueness rule and returned `ERR_DUPLICATE_RESOURCE` (HTTP 409) during setup. The duplicate check in the implementation is PRD-required and was left intact.

**Fixes applied to `implementation/`:** none. The bind-retry loop (`app.py::_wait_for_port_free`) and in-memory-only storage were verified present and correct.

**Final sweep:** Two consecutive 8-round parallel sweeps both passed 65/65 (passed == total, 0 failed, 0 errors) across all 8 rounds. Total test count: 65. Orchestrator re-confirmed all 8 results.{1..8}.json show passed=65 total=65 failed=0.

## Step 8: Finalize PRD — 2026-06-03T18:29:45.000Z

Both Step 7 fix sites trace to behavior the PRD already uniquely determines, so PRD_FINALIZED.md is a verbatim copy of PRD.md. This is the expected outcome flagged in the task note (Step 7 applied zero impl fixes and zero test deletions; both fixes were pure test-precondition bugs).

**Line counts:** PRD.md = 281 lines, PRD_FINALIZED.md = 281 lines. Delta: 0 lines (0.00%). Files byte-identical (orchestrator `diff -q` confirms IDENTICAL).

**Changes:** No edits — PRD already determines both Step 7 fix sites.

**Per-edit pre-edit search log (both sites investigated, no-edit conclusion):**

**Site A — §3.9 acceptance sweep (fixture clock-alignment fix).**
- (a) Subject: which transactions the acceptance sweep folds into `tax_due` — half-open period membership + "nexus accrued to this jurisdiction" / `SETTLED` / `SELLER` predicates.
- (b) Impl paths read: `routes/returns.py:128-165` (`_sweep_and_compute`); `services/settlement.py:76-142` (`settle`, `_sourced_state_id`); `:155-172` (`void` de-accrual); `:56-73` (`resolve_sourcing`).
- (c) No adjustment. PRD §3.9 (line 192) already states the four sweep predicates and the half-open `[period_start, period_end)` window the impl uses. Step 7 failure was a fixture settling its 100000.00 transaction with `created_at` inside the test's return period — precondition bug, not PRD silence.

**Site B — §126 ProductCategory (jurisdiction_id, category_code) uniqueness (redundant create_category fix).**
- (a) Subject: uniqueness on `(jurisdiction_id, category_code)` + `ERR_DUPLICATE_RESOURCE`.
- (b) Impl paths read: `routes/config.py:83-104` (`create_category` dup loop); `services/settlement.py:21-25` (`_category_for`) and `:96-97`.
- (c) No adjustment. PRD §126 (line 126) already states verbatim the uniqueness rule and `ERR_DUPLICATE_RESOURCE`. Step 7 fix removed redundant test-suite duplicate creates; impl is exactly PRD-prescribed.

**No-new-mismatch confirmation:** No PRD prose altered → no new universal claim → nothing for Step 9 to undo.

## Step 9: Complete PRD — full impl scan — 2026-06-03T18:34:03.000Z

**Source vs output:** `PRD_FINALIZED.md` (281 lines, 40,736 chars) → `PRD_COMPLETED.md` (281 lines, 41,236 chars). Char delta **+500**. Line count unchanged (all edits in-paragraph; orchestrator `diff` confirms 4 revised lines).

**Counts:** ambiguity-pins **4**, mismatch-revisions **0**. Total changes: **4**.

**Per-change list:**
- §2.4 (Common Resource Properties) — insert — ambiguity — pinned `version`'s initial value as **1** at creation — `services/common.py:182` (`stamp_create` sets version=1).
- §3.4 (Resolving sourcing) — insert — ambiguity — pinned that an `ORIGIN`-sourced settle where no jurisdiction matches the seller's `origin_state_code` is rejected with `ERR_INVALID_STATE` — `services/settlement.py:69-71`.
- §3.4 (Resolving each line's taxability) — insert — ambiguity — pinned that a line with no matching product-category row for sourced state + `category_code` is treated as fully taxable (`FULL`) — `services/settlement.py:96-97`.
- §3.5 (Nexus Accrual) — insert — ambiguity — pinned that when the seller has not opened a `NexusProfile` for the sourced state, settlement still succeeds and computes tax fields but performs no accrual — `services/settlement.py:131` (`if profile is not None`).

**Deliberately left unchanged** (verified consistent or out-of-scope): §2.1 ownership-check mechanism (impl does no per-endpoint seller-ownership enforcement; PRD sentence is conditional, not universal); §3.3/§3.8 ">2dp not rejected" (money-format guidance, not enforced validation, no test pins rejection); §2.6 `combined_rate` recompute (no jurisdiction-update endpoint exists); remittance validation order + accept-sweep filters (already match impl exactly).

Tests used only as auxiliary cross-reference; implementation was the sole alignment authority.

---

## PIPELINE COMPLETE — 2026-06-03T18:34:03.000Z

All 9 steps done. Final state: **65/65 tests pass across 8 consecutive stability rounds**. Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files), test_suite/ (conftest + 7 test files, 65 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}, workspace/implementation/ (Flask app, 48 endpoints, in-memory storage), results.{1..8}.json (all 65/65).
