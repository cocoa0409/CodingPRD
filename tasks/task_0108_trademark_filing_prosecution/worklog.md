# Worklog — task_0108_trademark_filing_prosecution

## Step 1: Create task directory — 2026-06-02T19:25:25.000Z

Created `tasks/task_0108_trademark_filing_prosecution/` and `tasks/task_0108_trademark_filing_prosecution/workspace/`. Index pre-assigned (0108); Step 1 index-scan skipped per run instructions.

## Step 2: Generate scaffold (Expert) — 2026-06-02T19:54:52.000Z

All three scaffold artifacts written and lint-clean (`scaffold_lint.py` → VERDICT: clean lint).

**Scale:** 13 entities, 51 endpoints, 17 validations (priority-ordered), 20 error codes, 4 roles, 2 OCC concurrency rules.

**Entities (13):** Applicant, Attorney, TrademarkApplication, NiceClass, GoodsServicesItem, OfficeAction, OfficeActionResponse, StatementOfUse, TTABProceeding, Registration, MaintenanceFiling, MadridApplication, DocketDeadline. Graph/flat topology; 14 FKs, all reverse-reachable in §1.5.

**State machines (4):** TrademarkApplication (cyclic: DRAFT→FILED→UNDER_EXAMINATION↔OFFICE_ACTION_ISSUED loop → PUBLISHED→{ALLOWED→REGISTERED (ITU/SOU) | REGISTERED (USE)}, + system ABANDONED); TTABProceeding (parallel claim_status × defense_status); Registration (maintenance loop revisiting ACTIVE, ACTIVE→GRACE→{ACTIVE|EXPIRED}); MadridApplication (PENDING_CERTIFICATION→CERTIFIED→FORWARDED_TO_WIPO, system CEASED via central-attack cascade).

**Key calculations (6):** application_filing_fee (tiered TEAS_PLUS/STANDARD × class, USE-vs-INTENT surcharge, surcharge-then-multiply order pinned); maintenance_fee (§8/§8&9 × class + grace surcharge); madrid_fee (base + per-country); docket_deadline_windows (response/opposition/answer/SOU/dependency offsets, finality-dependent grace tail); maintenance_window (registered_at-anchored §8/§9 windows w/ grace buffer); prosecution_risk_score (weighted, snapshot vs projected). All fee literals pre-computed.

**Difficulty design:** all 9 §0.5 rules × 2 instances (18). Dual-variant, combinatorial (modes a & c), cascades depth-3 (TTAB→Registration→Madrid) and depth-2 (OA-expiry→abandon→open-count), priority conflicts (state↔business_safety, business_constraint↔business_temporal), temporal-overlap (closed opposition interval vs buffered maintenance), 2 compensating invariants (open_application_count, PENDING-answer-deadline count).

**Corner design:** 28 active + 3 stubs.

**Note:** endpoint count 51 > Expert ceiling 32, driven structurally by 13 entities + 14 FK reverse-reachability GETs + 8 scenario sub-workflows mapping 1:1 to entities. Lint-clean overage retained per FK-reachability-overage guidance (trimming would drop scenario coverage/testability).

## Step 3: Copy INSTRUCTION.md — 2026-06-02T19:54:52.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0108_trademark_filing_prosecution/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-02T20:00:48.000Z

Generated `workspace/PRD.md` (~296 lines) from SCAFFOLD.yaml only; both design YAMLs withheld. 5 top-level sections (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue) + 17 subsections (§2.1–2.9, §3.1–3.8).

Hard-contract self-reports all PASS: field coverage (66/66 entity fields, 5/5 special params), rule coverage (priority-ordered validations, 2 OCC rules → ERR_STALE_VERSION/412, all 4 state machines incl. cascades + Madrid central-attack, 6 calculations reconstructible with exact constants, all 20 error_ids, side-effects, sibling-branch symmetry), path-purity (419 backtick tokens scanned, 0 paths/methods in §3). §4 table = 51 endpoints, §5 table = 20 errors. Withheld design files not opened.

## Step 5: Generate unit tests — 2026-06-02T20:15:19.000Z

Wrote `test_helpers/` (9 modules: types, api_client, api_errors [20 IDs], assertions, factories, constants, test_users, fixtures, __init__) and `test_suite/` (conftest + 9 domain test files). **65 tests total, all collect cleanly.**

Coverage: Queue A (Difficulty) = 36 tests covering all 18 instances × 2; Queue B (Corner) = 29 tests covering all 28 non-stub instances (≥1 each; 2 on timely_maintenance_fee). Every docstring ends with one verbatim `Design: Difficulty/...` or `Design: Corner/...` tag. Skips: only the 3 `excluded_because:` error-section stubs (no test_recipe; cross-refs resolve to real difficulty instances). No instances dropped for PRD-first filter — every rule had verbatim, uniquely-derivable PRD coverage. No skip/xfail; no scaffold leakage; 80 PRD-citation segments survive literal grep of PRD.md.

## Step 6: Generate implementation — 2026-06-02T20:15:19.000Z

Wrote `workspace/implementation/` — 22 Python modules (2,471 lines) + requirements.txt + start.sh (executable). All 51 PRD §4 endpoints registered in Flask URL map.

Modules: app.py (Flask entry, blueprints, error handlers, binds 0.0.0.0:$PORT foreground, default 10000); db.py (in-memory 13 entity dicts, logical clock override via /_clock/set_current_utc, registration-number sequence, NO seeding — empty on every boot, verified); errors.py/response.py/middleware.py (20 error IDs, meta/response_type/data envelope, 4-role auth Applicant/Attorney/Examiner/TTABClerk via X-User-ID/X-User-Role); services/ (models.py computed fields recomputed on read, calc.py fee/window constants+formulas, dateutil.py calendar-year offsets + days_late ceil, body.py, pagination.py, ownership.py); routes/ (9 resource modules: applicants/risk-score, attorneys, nice-classes, application lifecycle, office-actions/responses, SOU, TTAB, registrations/maintenance, Madrid, test clock).

Self-verification (60+ assertions passing): auth precedence 401→403→404, filing-fee tiers (USE/INTENT surcharge × TEAS_PLUS/STANDARD × class_count), finality-dependent OA grace-tail boundary, OCC ERR_STALE_VERSION on SOU/maintenance, INTENT→SOU→registration path, maintenance §8/§9 fees + grace surcharge, ACTIVE↔GRACE↔EXPIRED, TTAB cascades incl. depth-3 cancellation→registration→Madrid central-attack ceasing, snapshot/projected risk-score. Fixed during dev: approve-publication and issue-allowance initially omitted the status advance to PUBLISHED/ALLOWED — both corrected. start.sh reads $PORT, guards pip install on `import flask`, execs foreground.

## Step 7: Run tests and iterate — 2026-06-02T20:24:32.000Z

All 8 rounds pass 65/65 cleanly. The 8 `results.{1..8}.json` files are left in place (orchestrator re-verified: every round passed=65/total=65/failed=0).

**Iterations run:** 3 sweeps (1 baseline diagnosis + 2 verification sweeps after fixes).

**Tests deleted:** None. Every failure traced to a fixable test-helper/test-suite identity bug or a genuine implementation precedence bug — no test was PRD-silent or non-uniquely-derivable.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `create_attorney()` fixture: changed the calling header from `examiner_headers()` to `make_attorney_headers("creator")`. Why: PRD §4 authorizes `POST /attorneys` for the **Attorney** role only; the fixture used Examiner, so the PRD-faithful implementation correctly rejected it with `ERR_UNAUTHORIZED`, breaking the setup chain of ~57 tests.

**Fixes applied to `test_suite/`:**
- `test_suite/test_09_crud_rbac_and_envelopes.py` — 4 direct `api.create_attorney(..., examiner_headers())` call sites (in `test_foreign_applicant_flag_true`, `_parties()` helper, and `test_duplicate_attorney_bar_number_conflict`) switched to `make_attorney_headers("creator")`. Same root cause: wrong caller role for `POST /attorneys`. This made the request identity faithful to PRD without weakening any assertion.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/office_actions.py` — `submit_office_action_response()`: moved the already-closed guard (office action no longer `OUTSTANDING` → `ERR_ACTION_ALREADY_CLOSED`) **before** the application-state check. Why: on a duplicate response, the application has already returned to `UNDER_EXAMINATION`, so the generic state check fired first and returned `ERR_INVALID_STATE`. PRD §3.8 explicitly classifies "responding to an office action no longer OUTSTANDING" as the already-closed case yielding `ERR_ACTION_ALREADY_CLOSED`. Reordering is safe because office-action-OUTSTANDING and app-OFFICE_ACTION_ISSUED are equivalent states (no legitimate-rejection case is altered).

**Note on flakiness:** `test_maintenance_filing_before_window_opens_rejected` failed once with a transient `ConnectionError`/`BadStatusLine` on a clock POST (boot-time socket reset under 8× concurrent load), not a logic bug — its near-identical sibling passed alongside it, and it passed in 7/8 rounds and in both subsequent full sweeps.

**Final sweep status:** all 8 parallel rounds passed == total == **65/65**. The 8 `results.{1..8}.json` files remain on disk.

## Step 8: Finalize PRD — 2026-06-02T20:27:17.000Z

Produced `workspace/PRD_FINALIZED.md`. Line counts: PRD.md = 296, PRD_FINALIZED.md = 296 (0% delta; one line modified in place).

**Change (1):**
- §3.8 (Universal Validation Order) — *revise* — Appended a clause to the "Sixth, the already-closed guard" sentence pinning that the already-closed check is evaluated against the operative **child** resource's status (office action's `status` for a response; proceeding's `defense_status` for an answer) and is checked *ahead of* the fifth-stage parent-state check for these two operations — so a duplicate office-action response returns `ERR_ACTION_ALREADY_CLOSED` (not `ERR_INVALID_STATE`) even though the parent application has returned to `UNDER_EXAMINATION`. — `routes/office_actions.py:146-151` (and parallel `routes/ttab.py:135-143`).

**Step 7 items that produced NO PRD edit:** fixtures.py `create_attorney()` caller-role fix + test_09 four call-site fixes — pure test/fixture bugs. PRD §4 already pins POST /attorneys to Attorney role only, and `routes/attorneys.py:16` (`@require_roles("Attorney")`) matches exactly — neither silent nor mismatched, so no patch.

**Pre-edit search log (edit 1):** Subject = ordering between generic state check (ERR_INVALID_STATE) and already-closed guard (ERR_ACTION_ALREADY_CLOSED), and which resource's status each is evaluated against. Enumerated all raise sites: exactly two already-closed sites — office_actions.py:146-151 (already-closed on OA status before app-state check) and ttab.py:135-143 (already-closed on defense_status before claim-state/deadline checks). Wording scoped to "these two operations" / operative child resource; no universal claim, no global stage reorder — both sites described correctly, all other endpoints' fifth-stage state semantics untouched.

## Step 9: Complete PRD — 2026-06-02T20:34:07.000Z

Produced `workspace/PRD_COMPLETED.md`. Source PRD_FINALIZED.md (296 lines, 47,055 chars) → PRD_COMPLETED.md (296 lines, 48,672 chars), char delta +1,617, line count unchanged (all in-paragraph / in-table-row edits).

**Counts:** 11 ambiguity-pins, 0 mismatch-revisions (impl fully green 65/65 across all 8 rounds; every gap was silence, none a contradiction).

**Changes (11):**
- §2.7 — insert — ambiguity — Feb-29 anchor year-add into non-leap year clamps to Feb 28 — services/dateutil.py:24-30
- §2.7 — insert — ambiguity — Clock endpoint `data` carries single `current_utc` field echoing set instant — routes/system.py:23
- §3.4 — insert — ambiguity — No extension-grant endpoint exists → granted-extension count always 0, any `extension_number > 0` → ERR_SOU_NOT_PERMITTED; 0–5 range check (ERR_VALIDATION) precedes granted-count comparison — routes/statements_of_use.py:32,52-59
- §3.4 — insert — ambiguity — `registration_number` is a string — db.py:97-99, services/models.py:204
- §3.7 — insert — ambiguity — Madrid `fee_cents` is 0 on creation, stays 0 until certification locks it — routes/madrid.py:59,82
- §3.7 — insert — ambiguity — Madrid app against not-yet-filed basic application (filed_at null) → ERR_MADRID_COUNTRIES_INVALID — routes/madrid.py:50-51
- §3.7 — insert — ambiguity — Projected risk-score scopes +15 PENDING-deadline points to deadlines reachable from applicant (via application_id, or MAINTENANCE deadlines on owned registration) — routes/applicants.py:103-112
- §4 GET /applications — revise — ambiguity — Names optional applicant_id/attorney_id/status query filters — routes/applications.py:75-85
- §4 GET /applications/{id}/docket-deadlines — revise — ambiguity — Names optional status filter — routes/applications.py:304-309
- §4 GET /applications/{id}/office-actions — revise — ambiguity — Names optional status filter — routes/applications.py:321-326
- §4 GET /ttab-proceedings — revise — ambiguity — Names optional target_application_id/target_registration_id/petitioner_applicant_id filters — routes/ttab.py:109-119
- §4 GET /applications/{id}/registration — revise — ambiguity — Returns paginated array (zero or one registration), not single object — routes/applications.py:347-358

**Verified-consistent, left untouched:** open_application_count is derived/recomputed (no explicit-decrement pin needed); proceeding ownership scopes only Applicant role to petitioner_applicant_id (Attorney never blocked, proceedings carry no attorney_id); Madrid/proceeding/application creates do no ownership check on referenced non-mutated parents; office-action is_final is pure input (PRD's "second action on same ground marked final" is descriptive, not server-enforced).

---

## Pipeline complete

All 9 steps done. Final state: 13 entities, 51 endpoints, 65 tests, **8/8 sweep rounds green at 65/65**. Artifacts: SCAFFOLD.yaml + 2 design YAMLs, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/, workspace/implementation/ (22 modules + start.sh), results.{1..8}.json (all passing).
