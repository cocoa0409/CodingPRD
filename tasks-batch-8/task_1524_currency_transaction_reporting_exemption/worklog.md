# Worklog — task_1524_currency_transaction_reporting_exemption

## Step 1: Create Task Directory — 2026-08-13T18:07:00.000Z

Task directory `tasks/task_1524_currency_transaction_reporting_exemption/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per command args; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-13T19:20:00.000Z

**task_1524_currency_transaction_reporting_exemption — scaffold generated (harder-than-expert calibration)**

Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1524_currency_transaction_reporting_exemption/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys inside)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

Counts:
- Entities: 11 (Branch, Customer, CashTransaction, MonetaryInstrumentSale, DailyCashAggregation, CTR, ExemptionDesignation, StructuringAlert, ExaminationCase, ExaminationFinding, AuditEvent)
- Endpoints: 59 | State machines: 9 | Calculations: 7 | Validations: 32 (priorities 1–10) | Errors: 39 | Roles: 6 | OCC concurrency rules: 3
- §1.8 difficulty instances: 22 across all 9 rules (dual-variant ×2, combinatorial ×3 covering modes a/b/c, non-linear SM ×3, transitive cascade ×2 (depth-3 + depth-2, different triggers), priority-conflict ×2 (state-vs-temporal, safety-vs-constraint), boundary ×3 (CTR $10k strict->, $3k recordkeeping band floor, 5-qualifying-day count), cross-entity ×3, overlap ×2 (closed vs half-open interval semantics), compensating invariant ×2 (monetary sums, lineage cardinality))
- §1.9 corner instances: 62 total = 54 active + 8 excluded stubs citing §1.8 coverage

Lint verdict (verbatim tail): "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." (59 endpoints, 11 entities, 22 §1.8 + 54 §1.9 active instances, 592 calls scanned.)

Notable design decisions:
- Archetype compliance/audit + event-sourcing; flat topology; cyclic state machines (CTR revert+auto-AMENDMENT_REQUIRED, exemption annual-review cycle, finding remediation loop); segregation-of-duties role model (filer≠validator, approver≠requester, reviewer≠designator).
- Logical-clock endpoint (`POST /_clock/set_current_utc`, default 2026-08-01T00:00:00Z) drives deadlines, review-due sweep, void/amendment windows; all date math literals pre-computed with Python (due dates, 365-day review windows, 45-day amendment/revocation lookbacks).
- Pinned circular-dependency order: Phase II qualifying days read RAW reportability (ignoring exemption); coverage only gates actual CTR creation — enables the covered-days-still-count review proof.
- Cascades are transitive and audited: txn create/void → aggregation recompute → CTR auto-create/void/AMENDMENT_REQUIRED → per-transition SYSTEM AuditEvent on a sha256 hash chain with verify-chain endpoint.
- Every money figure in asserts pre-executed (e.g., fees 100100→501, 99900→500, per-item sum 1001 vs sum-then-round 1000; structuring score 40+16+18+15=89).
- No sibling task was inspected; design derived solely from the scenario + skill spec.

## Step 3: Copy Shared Files — 2026-08-13T19:22:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1524_currency_transaction_reporting_exemption/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T19:35:00.000Z

PRD generation is complete. Summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1524_currency_transaction_reporting_exemption/workspace/PRD.md` — 359 lines.

**Sections:**
- §1 Introduction (3 paragraphs: business context, exempt-person program, compliance perimeter)
- §2 Global Specifications: 2.1 RBAC (6 roles, `X-User-ID`/`X-User-Role`, opaque-identity prose for all roles); 2.2 Response envelope (byte-verbatim from the canonical source file, verified); 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 Logical clock, business dates, deadline arithmetic (default `2026-08-01T00:00:00Z`, 15/25/45/365-day and 5-year rules); 2.5 Common resource properties (incl. AuditEvent exception — no `updated_at`/`version`); 2.6 Nested resource retrieval (left-to-right per-entity 404s, body FK order); 2.7 Audit ledger and SHA-256 hash chain (genesis hash, canonical JSON, verify-chain); 2.8 Derived aggregations and recompute cascade (lazy rows, atomic consistency, trailing-45 propagation); 2.9 OCC (three rules with exact occ fields and HTTP 412); 2.10 Validation ordering (all 10 priority tiers with every error ID)
- §3 Business Logic: 3.1 Branch/Customer master data; 3.2 Cash transactions; 3.3 Instrument sales & recordkeeping (fee rule with the 100100/99900 disambiguation example); 3.4 Aggregation & CTR reportability cascade (pinned 4-step evaluation, Phase I vs Phase II coverage); 3.5 CTR lifecycle (validate/file/acknowledge/amend, `filed_late` vs `is_late`, supersede semantics); 3.6 Exemption designation & annual review (both eligibility variants, sweep to `REVIEW_DUE`, PASS/FAIL review); 3.7 Structuring detection (all 5 fire conditions, risk-score formula in prose, manual alerts); 3.8 Examination cases & findings (half-open scope overlap, remediation loop)
- §4 Endpoint table (59 endpoints, 4 columns only); §5 Error catalogue (39 errors, 2 columns only)

**Hard contract reports:**

```
Field coverage check:
- entities[].fields: 91 required, 91 present, 0 missing
- endpoints[].request_body/path_params: 66 required, 66 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 10 priority tiers expressed as an explicit ordered list, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 36 checked, 36 fully expressed (from→to, preconditions with error IDs, side effects), 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (aggregation, reportability, deadlines, fee with pinned round-then-sum, both eligibility variants, structuring score, hash chain), 0 missing
- validations[] conditions: 29 rules matchable to their error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed, 0 missing
- entities[].fields[] structured content: 91 fields' types/defaults/sources reconstructible, 0 missing
- sibling-branch symmetry: 8 sibling groups (e.g. 3 amendment sources, void rules for txn vs sale, PASS/FAIL review branches, Phase I/II coverage) at equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 527
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All 39 error IDs, 6 role names, 25 state values, and 57 enum values appear verbatim in backticks. The forbidden SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml files were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T19:55:00.000Z

Done. Final summary:

## Files written

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1524_currency_transaction_reporting_exemption/test_helpers/`):
- `__init__.py` — barrel export
- `types.py` — 11 entity TypedDicts (AuditEvent correctly omits `updated_at`/`version` per `common_fields: false`), 17 enums, 6-role `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~45 methods)
- `api_errors.py` — 39-entry `ApiErrorId` + `HTTP_STATUS_CODES`, registered with framework via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` shape validators
- `constants.py` — thresholds from the PRD calculations
- `factories.py` — input-only payload factories with sequence-unique codes
- `test_users.py` — opaque-role shared headers + per-instance `make_<role>_headers(user_id)` builders
- `fixtures.py` — composite helpers: `set_clock`, `setup_branch_and_customer`, `post_cash_txn`, `post_instrument_sale`, `create_ctr_in_draft` / `create_validated_ctr` / `create_filed_ctr`, `request_exemption` / `approve_exemption` / `create_active_phase_i_exemption`, `alert_in_status`, `exam_case_in_status`, plus CTR/aggregation readers

**`test_suite/`** (10 files, 98 test functions):
- `conftest.py` — session `api` fixture + per-role header fixtures
- `test_01_aggregation_and_reportability.py` (12 tests) — aggregation composition, CTR threshold boundary, fee calc, compensating invariant
- `test_02_ctr_lifecycle.py` (11 tests) — EFILE/PAPER dual-variant, revert + auto-AMENDMENT_REQUIRED, snapshot staleness, terminal lockdown, acknowledge, deadline boundaries, amendment lineage
- `test_03_cascades_and_audit.py` (5 tests) — txn→CTR cascade with audit-chain integrity, exemption-revoke cascade, genesis/verify-chain
- `test_04_exemption_lifecycle.py` (17 tests) — Phase II initial/review variants, qualifying-day boundary, sweep cycle, coverage evaluation order, phase/basis/duplicate, alert gating, priority pair, deny lockdown
- `test_05_structuring_alerts.py` (9 tests) — combinatorial score, detection conditions, dedup, manual window overlap, alert lifecycle
- `test_06_examinations_and_findings.py` (8 tests) — scope overlap (half-open, per-regulator), case cycle, finding revert loop, close guard, polymorphic target
- `test_07_validations.py` (16 tests) — shape, temporal, priority pair (state>temporal), business constraints, SoD
- `test_08_rbac_and_occ.py` (7 tests) — RBAC denials + read positive controls, three OCC rules
- `test_09_entities_and_listing.py` (13 tests) — creation defaults, computed fields, 404 family, FK order, pagination, cross-entity gating, instrument band floor/ceiling

## Test counts per queue
- **Queue A (Difficulty)**: 22/22 instances covered, each with ≥2 tests → **44 tests**
- **Queue B (Corner)**: 54/54 non-stub instances covered, each with ≥1 test → **54 tests**; 8 `excluded_because:` stubs correctly NOT translated (cross-references verified to resolve)
- **Total**: 98 tests; 0 untagged, 0 dual-tagged, 0 tags pointing at non-existent instances

## Instances skipped
None. Every instance in both queues has verbatim PRD coverage AND unique derivability, so no instance was dropped.

## Self-check results
- **Stage 1**: `test_helpers` imports cleanly; all 39 error ids registered; all 6 role headers emitted; composite fixtures cover every multi-step setup chain in the design indices.
- **Stage 2**: 98/98 tests collected by pytest; **142/142 PRD citations verbatim-grep PRD.md** (after fixing 5 citations that originally used ellipses to fuse sentence fragments — replaced with full multi-sentence quotes per the C3 rule); 0 `skip`/`skipif`/`xfail` markers; 0 scaffold/§1.x mentions in generated code (PRD-only references); 100% tag-to-instance resolution.

## Step 6: Generate Implementation — 2026-08-13T20:00:00.000Z

All checks pass. The implementation is complete and verified.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1524_currency_transaction_reporting_exemption/workspace/implementation/`):
- `start.sh` — executable launcher: guarded dependency install (`python3 -c "import flask"` check), then `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point: error handlers, blueprint registration, global request lock (atomic mutation + cascade), binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory store (plain dicts, starts completely empty; no seeding anywhere), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, ISO-8601 millisecond timestamp helpers, domain constants
- `errors.py` — `ApiError` + all 39 error IDs from the scaffold catalog
- `response.py` — envelope helpers matching the scaffold exactly (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta` for lists)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401/403), body/field validators, pagination parsing (limit default 10, min 1, max 100)
- `serializers.py` — exact per-entity field sets; CTR serializer derives DRAFT snapshots live from the aggregation and computes read-time `is_late`
- `services/audit.py` — append-only hash-chained ledger (sha256 of `prev_hash|seq|action|entity_type|entity_id|canonical_json(details)`, genesis = 64 zeros), `SYSTEM_AUTO`/`SYSTEM_SWEEP` event rules
- `services/domain.py` — daily aggregation recompute, CTR reportability cascade (auto-create DRAFT / auto-void DRAFT+VALIDATED / FILED+ACKNOWLEDGED→AMENDMENT_REQUIRED on snapshot divergence), structuring detector (5-day window, 5 fire conditions, risk score formula, closed-interval dedupe), Phase II eligibility (both variants), clock sweep to REVIEW_DUE
- `routes/` — 11 modules: clock, branches, customers, cash, sales, aggregations, ctrs, exemptions, alerts, exams, audit

**Endpoints implemented: 59/59** from the scaffold endpoint table (1 clock, 5 branch, 7 customer, 4 cash-transaction, 4 instrument-sale, 2 aggregation, 7 CTR, 7 exemption, 7 alert, 13 examination case/finding, 2 audit).

**State machines covered:** Branch (ACTIVE↔INACTIVE), Customer (ACTIVE↔SUSPENDED→CLOSED with open-items guard), CashTransaction and MonetaryInstrumentSale (POSTED/RECORDED→VOIDED, same-day window, distinct double-void errors), CTR (full lifecycle including system-driven VOIDED/AMENDMENT_REQUIRED and amendment supersede with CORRECTION successor), ExemptionDesignation (approve/deny/complete-review PASS+FAIL/revoke + clock sweep), StructuringAlert (review/dismiss/refer/reopen), ExaminationCase (fieldwork cycle + guarded close), ExaminationFinding (remediate/verify/reject).

**Calculations covered:** pinned per-instrument fee `max(150, round_half_up(amount*50/10000))` via `Decimal` ROUND_HALF_UP (verified the 100100+99900 → 1001 example), aggregation totals, raw-vs-covered reportability with Phase I/II directional coverage, EFILE+15/PAPER+25 deadlines with strict `23:59:59.999Z` lateness comparison, 45-day amendment window, 365-day eligibility windows (initial: ≥5 qualifying days AND ≥60 account age; annual: ≥5 days AND no referred alert), structuring risk score with all caps/bands, audit hash chain + verify-chain.

**Validations:** enforced in the scaffold/PRD priority order — auth → role → shape → existence (path left-to-right, body FK customer-before-branch) → OCC (`expected_customer_version`/`expected_ctr_version`/`expected_exemption_version` → 412) → state (409s, customer-before-branch on posting) → business safety (open-alert gate before SoD) → business constraints (422s) → temporal → snapshot-stale at file.

**Fresh-boot verification:** `bash start.sh` on a custom port boots cleanly, responds 401 without auth headers and 200 with them, store is empty (`total_count: 0`), `verify-chain` returns `{chain_valid: true, events_checked: 0}`, and repeated kill/relaunch cycles (simulating `--isolation per-test-server`) all boot and serve within ~2 seconds. Two end-to-end smoke suites (~100 assertions) covering every entity group, both happy paths and error paths, pass with zero failures.

## Step 7: Run Tests and Iterate — 2026-08-13T20:30:00.000Z

Clean sweep: 98/98 passed in all 8 parallel rounds. The task is complete.

**Iterations run:** 3 sweeps (24 total round-executions). Sweep 1: 15 deterministic failures × 8 rounds. Sweep 2: 3 flaky failures (connection-level). Sweep 3: all 8 rounds fully green (98/98 each).

**Tests deleted:** None. One assertion removed (partial-coverage split, STEP 1c):
- `test_04_exemption_lifecycle.py::TestPhaseIiEligibilityVariants::test_phase_ii_annual_review_window_ages_out_old_days` — removed the final `assert final["eligibility_snapshot"]["qualifying_day_count"] == 0`. Pattern: BRANCH-ASYMMETRIC SIDE EFFECT / two-reader divergence. PRD §3.6 pins snapshot storage to success paths only ("On approval ... the eligibility snapshot is stored"; "A passing review ... the fresh eligibility snapshot is stored"); whether a 422-rejected PASS attempt persists its evaluation snapshot is not stated, so faithful implementations diverge. (The test's own comment — "Initial variant snapshot is unchanged by the failed PASS attempt" — contradicted the assertion.) Covered assertions kept: `ERR_PHASE_II_INELIGIBLE` on the aged-out PASS attempt, `REVOKED`/`REVIEW_FAILED` on FAIL.

**Fixes applied to `test_helpers/`:**
- `factories.py::create_customer_payload` — added default `tin: "00-0000000"` (DEFAULTS["CUSTOMER_TIN"]). PRD §3.5 requires non-null customer `tin` before any CTR can be validated; the factory's no-tin default made every `create_validated_ctr`/`create_filed_ctr` setup violate that PRD precondition (root cause of 9 failures across test_02/07/08 — the triage-hint shared-fixture bug).
- `api_client.py::ApiClient.__init__` — session now sends `Connection: close`. The runner's per-test-server isolation SIGKILLs the server between tests on the same port while the session-scoped `requests.Session` pools keep-alive connections; reuse of a server-dead connection produced intermittent `ConnectionResetError`/`RemoteDisconnected`/`IncompleteRead` (3 flaky failures in sweep 2). Transport hygiene only; no PRD semantics. Verified zero tracebacks in our server logs — the server never crashed.

**Fixes applied to `test_suite/` (test bugs, STEP 2):**
- `test_02_ctr_lifecycle.py::test_efile_channel_marks_late_when_filed_after_efile_due`, `test_03_cascades_and_audit.py::test_txn_create_to_ctr_amendment_required_cascade` + `test_cascade_appends_system_auto_event`, `test_07_validations.py::test_amend_state_error_beats_temporal_error` — initial `set_clock` moved from `2026-08-01T09:00:00Z` to `2026-08-01T12:00:00Z`; each test posted transactions at 10:00, later than its own clock, so the implementation correctly rejected setup with `ERR_OCCURRED_AT_IN_FUTURE` (PRD §3.2 verbatim). Same business date, all downstream deadline/cascade assertions unchanged.
- `test_07_validations.py::test_ctr_incomplete_missing_tin_fixed_by_patch` — now passes `tin=None` explicitly to preserve its deliberate null-tin precondition against the new factory default.
- `test_09_entities_and_listing.py::test_instrument_sale_computed_fee_record_retention` — `retention_until` assertion changed from exact-string (`"2031-08-01T08:00:00Z"`) to parsed-instant equality. PRD §3.3 pins the instant ("exactly five years after `occurred_at`") but not the string format; §2.4's three-fractional-digit rule covers only logical-clock timestamps and `retention_until` derives from client input. Format was not uniquely derivable; instant equality is the maximal PRD-faithful assertion.

**Fixes applied to `implementation/`:** None. Every deterministic failure was a test-artifact bug; the implementation's PRD-required checks (`ERR_CTR_INCOMPLETE` TIN gate, `ERR_OCCURRED_AT_IN_FUTURE`) were correctly rejecting PRD-violating fixture requests, and no implementation check was weakened or removed.

## Step 8: Finalize PRD — 2026-08-13T20:40:00.000Z

Done. PRD_FINALIZED.md is produced with exactly two inline edits, both traced to Step 7 diff items.

**Line counts:** PRD.md = 359 lines; PRD_FINALIZED.md = 359 lines; 0% delta (both edits extend existing sentences inline; no sections added).

**Changes:**
- §3.3 — revise — extended the `retention_until` sentence to pin its serialization: ISO 8601 UTC with exactly three fractional digits, with the concrete example `2026-08-01T08:00:00Z` → `2031-08-01T08:00:00.000Z` — `implementation/routes/sales.py:114` (`fmt_dt(add_years(occurred_dt, 5))`), format from `implementation/db.py:80-83`.
- §3.6 — insert — after the sentence surfacing `ERR_PHASE_II_INELIGIBLE`/`ERR_PHASE_I_BASIS_INVALID` on a PASS review, added: the rejection is raised before any mutation, the designation remains `REVIEW_DUE` and retains the `eligibility_snapshot` from its last successful evaluation, and only approval or a passing review ever replaces the stored snapshot — `implementation/routes/exemptions.py:278-301` (raise at lines 284-289 precedes the snapshot write at line 295).

**Step 7 items requiring no edit:** the `factories.py` tin default and `test_07` explicit `tin=None` were pure fixture bugs (PRD §3.1/§3.5 already pin the non-null-tin validation gate); the four `set_clock` moves were test-setup bugs (PRD §3.2/§3.3 already pin `ERR_OCCURRED_AT_IN_FUTURE` verbatim); the `api_client.py` `Connection: close` change is transport hygiene with no API semantics; no `implementation/` fixes were applied.

**Per-edit pre-edit search log**

Edit 1 (§3.3 `retention_until` format)
- (a) Subject: serialization format of the client-instant-derived `retention_until` field.
- (b) Enumerated paths: grep for `retention_until|fmt_dt|add_years` across `implementation/` — sole write site `sales.py:114` at creation; `db.py:80-83` (`fmt_dt`: `%Y-%m-%dT%H:%M:%S.` + `%03dZ`), `db.py:136-140` (`add_years`); void path `sales.py:148-175` never touches it; `serializers.py:17-18` passthrough; list/get endpoints reuse the same serializer. Also checked sibling field `occurred_at` (`sales.py:106` stores the raw client string, unreformatted) and the date-derived fields (`due_date_efile`/`due_date_paper` via `due_date_str`, `db.py:126-127` — plain `YYYY-MM-DD`, unaffected).
- (c) Adjustment: scoped the format claim to `retention_until` only and dropped a draft contrast clause about `occurred_at` echo-as-received, to avoid pinning behavior beyond the Step 7 item. Leap-day behavior of `add_years` (Feb 29 → Feb 28) exists in impl but was not exercised by any Step 7 item, so it was deliberately left unpinned per hard scope.

Edit 2 (§3.6 rejected-PASS snapshot retention)
- (a) Subject: `eligibility_snapshot` lifecycle on a PASS review attempt rejected for eligibility failure.
- (b) Enumerated paths: grep for `eligibility_snapshot` — writes at `exemptions.py:135` (creation → null), `:206` (approve success; null for PHASE_I since `snapshot=None` at `:189`), `:295` (PASS review success; null for PHASE_I); non-writes verified by reading deny (`:223-250`), complete-review FAIL branch (`:302-307`), revoke (`:318-344`), clock sweep (`services/domain.py:389-411`), rejected approve (raises `:191`/`:194-199` before mutation at `:200+`), rejected PASS (raises `:284-289` before mutation at `:290+`); serializer passthrough (`serializers.py:47-48`). Also confirmed via `services/audit.py:60-80` that `add_fx` is request-scoped (`flask.g`) and `main_event` is unreachable on the raise path, so "before any mutation" holds with no audit side effect.
- (c) Adjustment: worded as a universal snapshot-replacement rule ("only approval and a passing review ever replace the stored snapshot") rather than a narrow review-only claim, after verifying it holds for every enumerated path (deny/FAIL/revoke/sweep/rejected attempts all retain; creation's initial null is not a "replacement"; PHASE_I stores null on success, consistent). No wording conflict with the existing §3.6 sentence "Whichever variant runs, the designation stores an `eligibility_snapshot` object…", which is scoped to the Phase II evaluation paragraph.

## Step 9: Complete PRD — 2026-08-13T20:55:00.000Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1524_currency_transaction_reporting_exemption/workspace/PRD_COMPLETED.md`.

**Source:** `PRD_FINALIZED.md` (existed; copied to PRD_COMPLETED.md). Note `PRD.md` and `PRD_FINALIZED.md` differ, so the finalized file was the correct base.

**Size:** 359 → 361 lines; 56,840 → 60,493 chars (**+3,653 chars**). 26 lines revised in place, 2 lines added (one new paragraph + blank line in §2.2). No sections added or removed.

**Counts:** 26 ambiguity-pins, 0 mismatch-revisions. Every state machine transition, threshold, formula (fee, risk score, eligibility windows), validation ordering, error code/HTTP status, filter set, and RBAC role list in the PRD was verified against the implementation and already matched — all changes pin behavior the PRD left unpinned.

**Changes (all insert/ambiguity):**

- §2.1 — insert — ambiguity — header values stripped of whitespace; blank-after-strip counts as missing — implementation/middleware.py:15-26
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock — implementation/response.py:9-13
- §2.2 — insert — ambiguity — unmatched route/method rejected with `ERR_INVALID_REQUEST` at 404/405 — implementation/app.py:41-50
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — implementation/middleware.py:109-129
- §2.3 — insert — ambiguity — `has_more` true exactly when offset + returned page size < total_count — implementation/response.py:26
- §2.4 — insert — ambiguity — clock set is unconditional (any instant, offsets normalized to UTC, bare date = midnight UTC) and responds 200 with `{"current_utc"}` — implementation/routes/clock.py:16-47, implementation/db.py:90-110
- §2.5 — insert — ambiguity — `version` starts at 1; `updated_at` initialized equal to `created_at` — implementation/db.py:143-150
- §2.7 — insert — ambiguity — system events carry `actor_id` null; cascade events appended as produced with the client call's event last; clock call's event uses `entity_type` `LogicalClock`, `entity_id` `logical-clock` — implementation/services/audit.py:60-86, implementation/routes/clock.py:40-46
- §2.7 — insert — ambiguity — `details` pinned to keys `before` (null on creation), `after`, `side_effects` (empty on system events) — implementation/services/audit.py:69-86
- §2.8 — insert — ambiguity — trailing-45 recompute = 45 UTC dates ending at current logical date, restricted to dates with an existing aggregation row — implementation/services/domain.py:228-241
- §3.1 — insert — ambiguity — duplicate `branch_code` rejected with `ERR_INVALID_REQUEST` — implementation/routes/branches.py:30-32
- §3.1 — insert — ambiguity — `account_opened_date` stored/returned verbatim as supplied — implementation/routes/customers.py:39-44
- §3.1 — insert — ambiguity — profile patch allowed in any status; null `legal_name` is a no-op, explicit null `tin` clears it — implementation/routes/customers.py:75-99
- §3.2 — insert — ambiguity — `conductor_name` defaults null; `occurred_at` stored verbatim — implementation/routes/cash.py:44,70
- §3.2 — insert — ambiguity — `void_reason` captured only in the void audit event's `side_effects`, never stored on the transaction — implementation/routes/cash.py:127-128
- §3.3 — insert — ambiguity — sale `occurred_at` stored verbatim — implementation/routes/sales.py:106
- §3.3 — insert — ambiguity — Feb 29 `occurred_at` yields Feb 28 `retention_until` in non-leap target years — implementation/db.py:136-140
- §3.3 — insert — ambiguity — sale `void_reason` audit-only, not stored on the sale — implementation/routes/sales.py:168-169
- §3.4 — insert — ambiguity — aggregation row persists/serializes the five flags `raw_reportable_in/out`, `covered_in/out`, `ctr_required` — implementation/services/domain.py:63-67, implementation/serializers.py:21-22
- §3.5 — insert — ambiguity — amendment appends a single AuditEvent with `entity_id` = successor CTR id; supersession summarized in `side_effects` — implementation/routes/ctrs.py:188-207
- §3.6 — insert — ambiguity — PHASE_I designations never run the Phase II evaluation; `eligibility_snapshot` stays null after approval and passing reviews — implementation/routes/exemptions.py:189,206,279,295
- §3.6 — insert — ambiguity — deny `reason` captured in audit `side_effects`; designation carries no denial-reason field — implementation/routes/exemptions.py:242
- §3.6 — insert — ambiguity — `review_note` captured in audit `side_effects`, not stored — implementation/routes/exemptions.py:275-276
- §3.6 — insert — ambiguity — revoke input `reason` captured in audit `side_effects` (resource keeps only the `MANUAL_REVOKE` code) — implementation/routes/exemptions.py:334
- §3.7 — insert — ambiguity — auto-created alerts append no AuditEvent of their own; summarized in the triggering call's `side_effects` — implementation/services/domain.py:325-326
- §3.7 — insert — ambiguity — audit-event list returns events in ascending `sequence_no` order — implementation/routes/audit.py:35-42
