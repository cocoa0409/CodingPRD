# Worklog — task_1554_gfsi_food_safety_certification_body

## Step 1: Create Task Directory — 2026-08-13T20:45:00.000Z

Directory `tasks/task_1554_gfsi_food_safety_certification_body/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline entry (Step 1 treated as DONE per command args). No index scan performed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T22:08:00.000Z

Scaffold generation complete. All three artifacts are written and the lint verdict is clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1554_gfsi_food_safety_certification_body/SCAFFOLD.yaml` — §1.0–§1.7 (response envelope verbatim; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1554_gfsi_food_safety_certification_body/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1554_gfsi_food_safety_certification_body/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

## Scaffold contents (SCAFFOLD.yaml)

- **12 entities**: Scheme (all rule constants as inputs), Client, Auditor (competency + conflict declarations + computed calibration), DecisionMaker (with `linked_auditor_id` driving segregation-of-duties), Application, Audit, Nonconformity, Certificate, ScopeChange, Appeal, WitnessAudit, DirectoryListing
- **47 endpoints**, including the logical-clock test driver `POST /certification-body/_clock/set_current_utc` (default `2026-08-01T00:00:00Z`) and the unauthenticated public `GET /directory`
- **40 error codes**, 9 ordered validation priorities, 5 roles (4 + Anonymous), 1 OCC concurrency rule (`certificate-scope-change-stale-occ` on `Certificate.version`, HTTP 412)
- 6 state machines: NC is cyclic (OPEN↔UNDER_REVIEW→CLOSED + OVERDUE), Certificate is branching-with-revert (ACTIVE↔SUSPENDED→WITHDRAWN/EXPIRED), Appeal/ScopeChange forked, Application/Audit guarded linear
- 7 calculations incl. dual-variant audit score (reported vs resolved, floor-halving on closure), dual-variant certification fee (quote vs invoice with pinned round-per-line-then-sum order), per-grade NC deadlines, calibration threshold, next-audit sequencing (every-Nth unannounced), and two clock-driven sweeps

## Design counts

- **Difficulty instances: 18** — exactly 2 per each of the 9 rules, each with fully structured `setup_api_calls` chains and code-computed literal assertions (e.g., reported 37 vs resolved 70; invoice 4000.00 vs 3999.99 rounding trap; deadline boundary at exact second; 30-day gap inclusive boundary)
- **Corner instances: 89** — 79 active (entities 18, state_machines 18, calculations 5, validations 19, endpoints 4, rbac 6, cross-cutting 6, consistency 1) + 10 `excluded_because` stubs referencing §1.8 instances (all verified resolvable)

## Verification

`scaffold_lint.py` verdict, pasted verbatim:

```
Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     79
  Calls scanned (§1.8+§1.9):  1197

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additionally verified: instance names unique across both design files (107), every error code referenced, no forbidden race vocabulary, enum closure clean (no dead enum values), and all date/fee/score literals computed via Python before being pinned in assertions.

## Step 3: Copy Shared Files — 2026-08-13T22:09:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1554_gfsi_food_safety_certification_body/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T22:31:00.000Z

All contracts pass. The PRD is complete and verified.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1554_gfsi_food_safety_certification_body/workspace/PRD.md` — 297 lines.

**Top-level sections:**
1. **Introduction** — 2 paragraphs (program context; independence + transparency commitments, logical clock)
2. **Global Specifications & System-Wide Principles** — 2.1 RBAC (5 roles with identity semantics), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Request Evaluation Order (all 9 validation priority classes with error ids), 2.6 Logical Clock & Scheduled Sweeps, 2.7 Independence/Conflicts/Segregation of Duties, 2.8 Audit Window Geometry, 2.9 Scoring, Fees & Rounding, 2.10 Certificate Status Propagation & Public Directory, 2.11 Optimistic Concurrency Control
3. **Business Logic & Workflows** — 9 subsections: scheme constants; onboarding (clients/auditors/decision makers/witness calibration); application lifecycle; assignment & scheduling; audit conduct & findings; certification decision & audit chain; CAP/nonconformity cycle; certificate suspension/reinstatement/withdrawal/expiry; scope changes, appeals & public directory
4. **Endpoint Definitions** — 47-row table (Method/Path/Description/Roles only)
5. **Error Code Catalogue** — 40-row table (Error ID/HTTP Status only)

**Hard-contract verification (mechanical, via Python against the scaffold):**
- **Contract 1 (Field-Name Coverage): PASS** — 79/79 entity fields and 56/56 endpoint input/query identifiers present in backticks (90-name deduplicated set, 0 missing).
- **Contract 2 (Rule Coverage): PASS** (manual audit) — validation priority order expressed as a 9-class ordered list; the OCC rule names endpoint, `expected_certificate_version`, and `ERR_STALE_CERTIFICATE_VERSION`/412 in stale-version terms only; all 22 state transitions, all 7 calculations (both audit-score variants with 25/10/3 weights and 12/5/1 floored halves, quote/invoice fee variants with pinned round-per-line-then-sum order, NC deadline with strict-greater overdue, calibration with inclusive boundary, next-audit projection, both sweeps with `created_at` ASC processing and no-drift), all cross-entity cascades, and all four GRANT/DENY × audit-type decision branches are in prose with no pseudocode and no fuzzy wording.
- **Contract 3 (§3 Path Purity): PASS** — 445 backticked tokens scanned, zero paths/methods/combos.
- Supporting checks: all 40 error ids appear in §2/§3; all 41 enum values appear as standalone backticked strings (fixed `DECIDED` from an arrow pair to standalone); §4 row count matches 47 scaffold endpoints; §5 row count matches 40 errors.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Resume Assessment — 2026-08-13T22:50:00.000Z

Resume run audit of prior partial run:
- Step 1 (task dir): DONE — pre-created.
- Step 2 (scaffold): COMPLETE — SCAFFOLD.yaml (70KB), SCAFFOLD_DIFFICULTY_DESIGN.yaml (106KB), SCAFFOLD_CORNER_DESIGN.yaml (265KB), clean lint verdict recorded. Kept.
- Step 3 (INSTRUCTION.md): COMPLETE — workspace/INSTRUCTION.md present. Kept.
- Step 4 (PRD): COMPLETE — workspace/PRD.md (297 lines, 51KB), all hard contracts PASS per prior entry. Kept.
- Step 5 (unit tests): NOT STARTED — test_suite/ and test_helpers/ absent. Must run.
- Step 6 (implementation): TRUNCATED mid-generation — only middleware.py, errors.py, response.py, start.sh, requirements.txt, db.py, services/core.py, routes/{registration,applications,audits,nonconformities}.py exist; NO app.py, no certificates/scope_changes/appeals/witness_audits/directory/clock routes (scaffold declares 47 endpoints). Must REGENERATE.
- Steps 7-9: NOT STARTED.

Plan: launch Step 5 (test gen) and Step 6 (impl regen) concurrently, then Steps 7-9.

## Step 6: Regenerate Implementation — 2026-08-13T23:15:00.000Z

The implementation is complete and verified. Final summary:

## Summary

**Task**: Complete the truncated implementation for `task_1554_gfsi_food_safety_certification_body`.

### Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1554_gfsi_food_safety_certification_body/workspace/implementation/`)

**Written new (were missing):**
- `app.py` — Flask assembly, blueprint registration under `/certification-body`, `ApiError`/404/405/500 handlers all emitting the scaffold envelope, `static_folder=None`, `PORT` env (default 10000), binds `0.0.0.0`
- `routes/certificates.py` — certificates list/get (filters + ClientAdmin scoping), suspend (manual, `reason` required), reinstate (NC-guard for `NC_OVERDUE`/`CAP_REJECT_LIMIT`, guard-free for `MANUAL`), withdraw, scope-changes create (OCC `expected_certificate_version` → 412, certificate version bump on create) + list, appeals list, directory-listing
- `routes/scope_changes_appeals.py` — scope-change decision (approve replaces cert categories + bumps cert version + regenerates `scope_summary`), appeals create (ref → ownership → cert state → inclusive appeal-window → duplicate, in §2.5 priority order) and appeals decide (independence: original DM and linked auditor barred; OVERTURNED reinstates cert + re-lists)

**Kept from the partial run, verified consistent, and hardened:** `start.sh` (guarded pip install + `exec`), `requirements.txt`, `db.py` (empty stores, logical clock defaulting to 2026-08-01T00:00:00Z, ISO-8601 ms serialization), `errors.py` (all 39 error IDs), `response.py` (envelope + `limit`/`offset` pagination with 1–100 clamp), `middleware.py` (added `body_preflight` so role/existence/state checks precede field-level 400s per §2.5), `services/core.py`, and the 4 existing route files (added preflight calls; removed auditor `version` bumps on cascades since the scaffold never declares them; stopped persisting `review_notes` since it is not a declared entity field). Pyflakes-clean; no seeding anywhere.

### Verification results
- **Endpoint coverage: 47/47** (enumerated from the live Flask app; matches the scaffold endpoint table exactly)
- **State machines (6)**: Application, Audit, Nonconformity (incl. OVERDUE sweep and CAP-reject-limit cascade), Certificate (suspend/reinstate/withdraw/expire + appeal reinstate), ScopeChange, Appeal — plus DirectoryListing LISTED↔UNLISTED propagation on every transition
- **Calculations (7)**: `audit_score` reported/resolved (full vs floor-halved weights, clamped at 0), `certification_fee` quote/invoice (Decimal, ROUND_HALF_UP, round-per-line-then-sum; verified 333.33×1.5 → 500.00 line), `nc_deadline`, `auditor_calibration_status` (inclusive boundary), `next_audit_sequence_and_type` (max() window projection, UNANNOUNCED on seq % n == 0), `overdue_nc_sweep` and `certificate_expiry_sweep` (strict `>`, created_at ASC, no re-transition drift)
- **Boot test**: `PORT=55389 bash start.sh` boots in ~2s; 155-check main e2e suite and 52-check edge-case suite each pass 100% on their own fresh boots, covering auth/RBAC/ownership, all error IDs exercised (including `ERR_AUDIT_UNASSIGNED` reachability, `ERR_APPEAL_WINDOW_EXPIRED` masking `ERR_DUPLICATE_APPEAL`, inclusive window/appeal/calibration boundaries, exclusive expiry/overdue boundaries, rotation limit, overlap inclusive-touch, min-gap, OCC 412, and the full GRANT/DENY × INITIAL/SURVEILLANCE/UNANNOUNCED fork matrix)

## Step 5: Generate Unit Tests — 2026-08-13T23:35:00.000Z

Generation complete. All checks pass. Final summary:

## Summary

**Task**: test infrastructure + test cases for `task_1554_gfsi_food_safety_certification_body`, generated strictly from the two design indices against the PRD contract.

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — 12 entity TypedDicts + 15 enums (all entities carry common fields per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (47 total, `/certification-body` prefix)
- `api_errors.py` — 40 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*`, plus `assert_instant_equal` (instant-level timestamp comparison, tolerating the PRD §2.4 three-fractional-digit rendering vs the design index's bare `...Z` notation) and `assert_money`
- `factories.py` — payload factories, input fields only; `constants.py` — pinned scheme constants, score weights, derived window/validity instants
- `test_users.py` — opaque `TEST_USERS` constants + per-instance builders `make_client_admin_headers` / `make_auditor_headers` / `make_decision_maker_headers` for the three entity-backed roles
- `fixtures.py` — 5-tier composite chains: `setup_accepted_chain` → `setup_assigned_chain` → `setup_started_chain` → `setup_reported_chain` → `setup_granted_chain`, plus `start_second_audit`, NC CAP helpers (`close_nc`/`reject_nc`), certificate/appeal/scope-change helpers, all identity-threaded

### Stage 2 — `test_suite/` (conftest + 10 files, 115 tests)
| File | Tests |
|---|---|
| test_01_envelope_and_registration.py | 7 |
| test_02_read_paths_pagination.py | 12 |
| test_03_applications.py | 11 |
| test_04_assignment_windows.py | 21 |
| test_05_audit_execution.py | 11 |
| test_06_scoring_decisions.py | 13 |
| test_07_fees.py | 4 |
| test_08_nonconformities.py | 13 |
| test_09_certificates_directory.py | 15 |
| test_10_appeals.py | 8 |

### Coverage audit
- **Queue A (Difficulty)**: 18/18 instances covered, exactly 2 tests each (36 tests). 0 skipped.
- **Queue B (Corner)**: 79/79 non-stub instances covered, 1 test each (79 tests). 0 skipped. The 10 `excluded_because:` stubs were not translated; all 10 `difficulty_instance` cross-references resolve to real §1.8 instances.
- **No instance failed the PRD-first two-condition filter** — every asserted rule (including the four priority-ordering instances, justified by PRD §2.5's explicit nine-class masking order) has verbatim PRD coverage and a uniquely derivable outcome.

### Citation/tag verification (scripted)
- Every one of the 115 docstrings ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line copied verbatim from the source YAML; zero untagged, zero double-tagged, zero unresolvable tags.
- All 153 quoted PRD citation fragments survive literal (whitespace-normalized) matching against `PRD.md`.
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in generated code.
- All files compile; `pytest --collect-only` gathers 115 tests; pyflakes clean on `test_suite/`.

## Step 7: Run Tests and Iterate — 2026-08-13T23:55:00.000Z

Clean 8-round sweep achieved: **115/115 passed, 0 failed, 0 errors in every round** (verified via both pytest summaries and all 8 `results.*.json` files).

## Summary

**Iterations run:** 2 (first sweep surfaced the flakiness; second sweep after fixes passed 8/8).

**Tests deleted:** None. Both failing tests traced to verbatim PRD rules and were kept at full assertion strength.

**Failures found (union across first 8-round sweep):**
1. `test_02_read_paths_pagination.py::TestPaginationAndFilters::test_list_applications_pagination_limit_offset` — failed in rounds 1, 3, 4, 6. Assertion `data1[0]["id"] == app1["id"]` tripped.
2. `test_04_assignment_windows.py::TestActiveAuditCountConservation::test_active_count_cancel_compensates` — failed in rounds 2, 3, 4, 5 with `ConnectionResetError` / `RemoteDisconnected` at varying fixture-setup steps (once on the very first request).

**Fixes applied to `implementation/`** (all in `/home/ubuntu/github/CodingPRD/tasks/task_1554_gfsi_food_safety_certification_body/workspace/implementation/`):
- `routes/applications.py`, `routes/audits.py`, `routes/certificates.py`, `routes/registration.py`, `services/core.py` — removed the random-UUID `id` tie-break from every list/sweep sort (14 sort sites). Under the PRD's frozen logical clock (§2.6), entities created in the same test share `created_at`, so `(created_at, id)` sorted non-deterministically (reproduced 5/8 standalone). The PRD-covered rule is "created_at ascending" (§2.3/§3.3); Python's stable sort over the insertion-ordered in-memory store now resolves ties by creation order deterministically. Verified 10/10 insertion-order reproductions post-fix.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — `ApiClient.__init__` now sets `session.headers["Connection"] = "close"`. The runner SIGKILLs and respawns the server on the same port before every test (per-test-server isolation); the session-scoped client's keep-alive pool held dead connections that intermittently reset on reuse (requests' default adapter never retries POSTs). A fresh TCP connection per request eliminates the stale-pool draw. No assertion changed; this is robustness of the test artifact to the runner's documented restart behavior.

**Fixes applied to `test_suite/`:** None needed — both tests were faithful to PRD.

## Step 8: Finalize PRD — 2026-08-14T00:05:00.000Z

Done. PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1554_gfsi_food_safety_certification_body/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts:** PRD.md = 297 lines, PRD_FINALIZED.md = 297 lines (0% line-count delta; the single change is an in-paragraph insertion of two sentences on line 72).

**Changes (1 total):**
- **§2.3 Pagination** — *insert* — added: "Because the logical clock (§2.6) holds its value until explicitly advanced, resources created between two clock advances share the same `created_at`; wherever the system orders resources by `created_at` — whether as a list's primary ordering, as a stated tie-break, or in the sweep candidate processing of §2.6 — such ties are resolved by creation order, so a resource created earlier precedes one created later." — impl: `routes/applications.py:117`, `routes/registration.py:109,319,370`, `routes/audits.py:327,462`, `routes/certificates.py:79,250,270`, `services/core.py:122,474,495` (all stable `created_at` sorts over the insertion-ordered in-memory dicts in `db.py:17-28`).

The second step_7_diff item (`test_helpers/api_client.py` `Connection: close` header) is a test-artifact robustness fix against the runner's per-test server restarts — it pins no API behavior, so it required no PRD edit.

## Pre-edit search log (mandatory, for the single edit)

**(a) Subject:** ordering tie-break when `created_at` values are equal, across list endpoints and sweeps.

**(b) Impl paths enumerated and read/grepped** (grep for `sort|sorted` across `routes/*.py`, `services/*.py`; each site read in context):
- `routes/applications.py:117` — list applications, `created_at` only, stable
- `routes/applications.py:256` — audits of application, `sequence_number` only
- `routes/registration.py:109` — list schemes, `created_at` only, stable
- `routes/registration.py:227` and `:349` — auditor's audits / decision-maker's decided audits, `(sequence_number, created_at)`, stable
- `routes/registration.py:275-276` — witness audits, `created_at` ASC then `witnessed_on` DESC (stable), so full ties fall to creation order
- `routes/registration.py:319` — list decision makers, `created_at` only
- `routes/registration.py:370` — public directory, `created_at` only
- `routes/audits.py:153` — rotation chain, `sequence_number` DESC, no `created_at` involvement
- `routes/audits.py:327` — findings of audit, `created_at` only
- `routes/audits.py:462` — certificate-of-audit array, `created_at` only
- `routes/certificates.py:79,250,270` — certificates / scope-changes / appeals lists, `created_at` only
- `services/core.py:122` — `find_certificate_for_client_scheme` helper, `created_at` only
- `services/core.py:146` — `audits_for_client_scheme`, `sequence_number` only
- `services/core.py:366` — `scope_summary` alphabetical code sort (not `created_at`)
- `services/core.py:474,495` — overdue-NC and expiry sweep candidates, `created_at` only
- `db.py:17-28` — all stores are plain dicts (insertion-ordered); `response.py:82` `paginate` does not re-sort

**(c) Wording adjustment:** The sentence was deliberately scoped to "wherever the system orders resources by `created_at`" — explicitly covering primary list orderings, stated tie-breaks (witness audits' `created_at` ASC secondary key, and the `(sequence_number, created_at)` auditor/decision-maker audit lists), and §2.6 sweep candidate processing — while saying nothing about `sequence_number`-keyed orderings (rotation chain, per-application audit chains) or the alphabetical `scope_summary` sort, none of which order by `created_at`. It also avoids claiming any UUID/`id` comparison (the pre-fix behavior Step 7 removed) and avoids asserting anything about cross-`sequence_number` tie-breaking beyond what the impl does.

## Step 9: Complete PRD — 2026-08-14T00:25:00.000Z

All edits are in place and verified against the implementation. PRD_COMPLETED.md is complete.

## Summary

**Source**: `PRD_FINALIZED.md` (existed) → copied to `PRD_COMPLETED.md`, then edited only the copy.
**Size**: 297 → 299 lines; 51,449 → 54,182 chars (char-delta **+2,733**).
**Counts**: 20 edit operations — **15 ambiguity-pins**, **5 mismatch-revisions** (some pins cover multiple behaviors in one clause).

### Changes (PRD section — edit — class — what changed — impl ref)

- §2.1 — insert — ambiguity — entity-backed `X-User-ID` is never verified against a registered record; ownership/independence compare identifier values only — `middleware.py:16-32`
- §2.1 — revise — ambiguity — on the public directory, missing *or unrecognized* headers yield an `Anonymous` caller rather than 401 — `middleware.py:24-26`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) and negative/non-integer `offset` are rejected `ERR_INVALID_REQUEST` (400) — `response.py:52-79`
- §2.4 — revise — ambiguity — `version` starts at **1** on creation — `db.py:109-112` and every entity literal `"version": 1`
- §2.5 (classes 3/4) — revise — **mismatch** — impl checks *path existence before ownership* on all endpoints (PRD had ownership first), with the sole exception of reading a client record — e.g. `audits.py:74-77` vs `registration.py:153-162`
- §2.5 (class 4) — insert — **mismatch** — appeal creation runs the `certificate_id` body-reference check (class 6) *before* ownership — `scope_changes_appeals.py:96-106`
- §2.5 (class 6) — revise — ambiguity — `scheme_id` on application creation added to the body-reference check list — `applications.py:55-59`
- §2.5 (closing note) — insert — ambiguity — placement of `ERR_INVALID_REQUEST` (400): non-object body rejected right after role auth (before existence) except witness-audit recording which resolves its path first; field/type/enum 400s surface where the body is consumed (creation endpoints after role auth; transition endpoints after class-5 state, except application review which validates `outcome` first); body-less endpoints (submit, start, cancel, reinstate, withdraw) ignore the body — `middleware.py:51-71`, `applications.py:158-173`, `registration.py:236-246`
- §2.6 — revise — ambiguity — unparseable `to_iso8601` → 400; any instant settable (earlier or later); *every* set fires both sweeps — `registration.py:382-394`
- §2.7 — insert — ambiguity — a `DecisionMaker` X-User-ID matching no registered record carries no `linked_auditor_id` and passes independence checks — `audits.py:384-396`, `scope_changes_appeals.py:181-192`
- §2.8 — insert — ambiguity — cancelled sibling audits are disregarded in the `min_audit_gap_days` separation check — `core.py:270-293`
- §3.2 — revise — ambiguity — `competency_categories` may be empty — `registration.py:176-180`
- §3.2 — revise — ambiguity — calibration uses the *smallest* `witness_validity_days` across all registered schemes (auditors have no single scheme); always `LAPSED` when no scheme is registered — `core.py:155-178`
- §3.2 — insert — ambiguity — `linked_auditor_id` recorded as supplied, without reference validation — `registration.py:294-296`
- §3.3 — insert — ambiguity — unknown `scheme_id` → `ERR_REFERENCE_NOT_FOUND` (422); duplicate category codes permitted, each entry counted separately in per-category fee math — `applications.py:55-59`, `core.py:49-75`
- §3.3 — revise — ambiguity — review `outcome` enum pinned to `ACCEPTED`/`REJECTED`; `rejection_reason` optional, null when omitted, absent from the record until a rejection is recorded — `applications.py:161-181`
- §3.4 — revise — ambiguity — rotation counts only `DECIDED` audits, ranked most-recent-first by `sequence_number` — `audits.py:138-163`
- §3.4 — revise — **mismatch** — reschedule check order is well-formedness → auditor-overlap → sibling-gap (PRD listed gap before overlap); unparseable window bound → `ERR_INVALID_AUDIT_WINDOW` — `audits.py:189-197`, `core.py:213-244`
- §3.5 — revise — ambiguity — `actual_days` must be an *integer* of at least 1 — `audits.py:349-357`
- §3.6 — insert — ambiguity — certificate-number sequence starts at CERT-000001 — `db.py:30,49-52`
- §3.7 — revise — **mismatch** — `review_notes` is validated but *not persisted* on the finding (PRD said "attach") — `nonconformities.py:103-105`
- §3.8 — revise — **mismatch** — `suspension_reason` lifecycle: null at issuance, set on suspension, cleared on reinstatement, *left unchanged* by withdrawal and expiry (PRD had "null unless SUSPENDED") — `core.py:385-412`
- §3.8 — insert — ambiguity — reinstatement leaves `valid_from`/`valid_to` unchanged — `core.py:393-398`
- §3.9 — insert — ambiguity — `OVERTURNED` reinstatement likewise leaves validity bounds unchanged — `scope_changes_appeals.py:200-211`

No new sections were added; one new closing paragraph inside existing §2.5 (the only cross-cutting behavior with no host paragraph). Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1554_gfsi_food_safety_certification_body/workspace/PRD_COMPLETED.md`.
