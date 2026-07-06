# Worklog — task_0752_public_notice_legal_ads

## Step 1: Create task directory — 2026-07-05T00:00:00.000Z

Task directory pre-assigned: `tasks/task_0752_public_notice_legal_ads` (Expert difficulty). `workspace/` subdir already present. No new ID created.

## Step 3: Copy shared files — 2026-07-05T00:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0752_public_notice_legal_ads/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-07-05T00:00:00.000Z

Generated a complete Expert-difficulty scaffold for the Public-Notice & Legal-Advertising Platform (task 0752). All three files parse as valid YAML and `scaffold_lint.py` returns **`VERDICT: clean lint`** (34 endpoints, 10 entities, 18 §1.8 + 25 §1.9 instances, 452 calls scanned, 0 violations).

**Files written (absolute paths):**
- `SCAFFOLD.yaml` — 1314 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1335 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1184 lines

**Design shape:** compliance/audit primary archetype blended with a pricing engine; hybrid topology with a self-referential make-good FK; compound/cyclic state shape; peer-role RBAC (Advertiser=entity_backed:Account, Publisher=entity_backed:Newspaper, plus opaque ComplianceOfficer/PlatformAdmin).

**Counts:** 10 entities · 34 endpoints · 5 state machines · 5 calculations · 10 validations · 19 errors · 4 roles · 1 OCC concurrency rule (schedule supersede). §1.8 covers all 9 difficulty rules × 2 instances (18); §1.9 has 25 full corner instances + 5 excluded-because stubs across all 10 taxonomy sections; 48 instance names, all unique.

**Notable mechanics driving difficulty:** dual-variant notice_cost (estimated vs final) and account_balance (outstanding vs committed) on different entity domains; combinatorial per-insertion-ceil rounding (mode b) plus affidavit-fee waiver keyed on subtotal tier (mode c); depth-3 publish cascade (insertion→notice→invoice→account) and depth-2 void compensation; two temporal-overlap semantics (edition aggregate line-capacity vs exact consecutive-week adjacency); conserved-quantity invariants over money (outstanding_balance) and count (paid_insertion_count via the skip/make-good mechanism); a logical clock (default `2026-03-01T00:00:00Z`) making all deadline/publication rules deterministic. `api_prefix` set to `/` (flat multi-root API); single-resource GETs added for Payment and InvoiceLineItem so every FK has reverse-reachability.

## Step 4: Generate PRD — 2026-07-05T00:00:00.000Z

**Output:** `workspace/PRD.md` — 252 lines.

**Sections covered:** §1 Introduction; §2 Global Specs (2.1 RBAC with all four roles + entity-backed/opaque identity translation, 2.2 verbatim response envelope, 2.3 pagination, 2.4 identity/timestamps/versioning incl. `InvoiceLineItem`/`Payment` having no `updated_at`/`version`, 2.5 OCC on schedule with `expected_notice_version`/`ERR_STALE_VERSION` 412, 2.6 money+pricing basis, 2.7 logical clock, 2.8 nested-path resolution, 2.9 validation ordering); §3 workflows scattered across 8 subsections (provisioning → draft/submit+credit gate → proofing revision cycle → scheduling/reschedule/manual-insertion/cancel → publish/skip/make-good → completion+compliance+final cost → affidavit/invoice/void/payments/balances → archive); §4 four-column endpoint table (34 endpoints); §5 two-column error catalogue (19 codes).

**Hard-contract reports:** Contract 1 (Field-Name Coverage) PASS — 0 missing. Contract 2 (Rule Coverage) PASS — 5 calculations, 10 priority-ordered validations, 21 state transitions, 1 OCC rule all in precise prose. Contract 3 (§3 Path Purity) PASS — 0 slash/HTTP-method tokens in §3.

## Step 5: Generate unit tests — 2026-07-05T00:00:00.000Z

**Test files:** 6 (`conftest.py` + 5 `test_*.py`), **61 tests total**, collected cleanly.

**Queue coverage:** Queue A (Difficulty) 36 tests — all 18 difficulty instances (9 rules × 2) × 2 tests apiece. Queue B (Corner) 25 tests — all 25 non-stub corner instances × 1 test. **Skipped instances: 0.** 5 `excluded_because:` corner stubs correctly NOT translated (assertions owned by cited difficulty instances). Validation-priority-conflict instances survived on PRD §2.9 + §3.4 ordered prose.

**Audits passed:** every docstring carries exactly one verbatim `Design:` line; PRD citations survive literal grep; no scaffold leakage.

**test_helpers/ (9):** `__init__.py`, `types.py` (InvoiceLineItem/Payment omit updated_at/version), `api_client.py`, `api_errors.py` (19-error catalog + http status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance entity-backed header builders), `fixtures.py` (composite lifecycle helpers provision→proof→scheduled→running→published→affidavit→invoice_paid + skip/make-good, built per-test).

## Step 6: Generate implementation — 2026-07-05T00:00:00.000Z

Complete Python + Flask in-memory REST API. Files under `workspace/implementation/`: `start.sh` (set -euo pipefail, guarded flask install, reads $PORT default 10000, binds 0.0.0.0, foreground exec), `requirements.txt` (flask==3.0.3), `app.py` (factory, envelope error handlers, threaded), `store.py` (in-memory dicts, logical clock default 2026-03-01T00:00:00Z, light records for InvoiceLineItem/Payment), `core.py` (envelope/auth/typed body parse/pagination/serializers), `domain.py` (pricing, scheduling geometry, publish bubble-up, invoice+3000¢ affidavit-fee waiver, compliance, balances), `routes.py` (all endpoints, §2.9 check ordering).

**Endpoints: 34** (full §1.5/§4). Storage in-memory only, starts empty (no seeding), per-test-server restart wipes state. Smoke-tested happy path + all error branches.

**Spec-conflict flag (for Step 7):** account `outstanding_balance` literal aggregate excludes PAID-invoice totals while still subtracting all payments → negative balance after full payment (e.g. -4500), contradicting incremental state-machine deltas + PRD "a paid invoice's total is already netted out by its payments." Impl used self-consistent closed form `outstanding = Σ(total over ISSUED∪PAID) − Σ(all payments)` → fully-paid nets to 0. Flip point: single line in `domain.account_balances` if tests assert the literal aggregate.

## Step 7: Run tests and iterate — 2026-07-05T00:00:00.000Z

- Iterations run: 1 (single 8-round parallel sweep).
- Result: All 8 rounds passed **61/61** tests — 0 failed, 0 errors, 0 skipped in every round. No flakiness surfaced across the concurrent sweep (verified independently: results.1..8.json all passed=61 total=61 failed=0 errors=0).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.
- No diagnostic protocol steps were needed. The flagged `outstanding_balance` spec question did not surface as a failing test, so no interpretation decision was required.

## Step 8: Finalize PRD — 2026-07-05T00:00:00.000Z — SKIPPED

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at every Step-7 site. `PRD_FINALIZED.md` is intentionally absent; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-05T00:00:00.000Z

**Source vs output:** PRD.md = 252 lines / 36,920 chars → PRD_COMPLETED.md = 252 lines / 38,459 chars (Δ +1,539 chars; all in-paragraph inserts/revisions, no new sections).

**Counts:** 5 ambiguity-pins, 3 mismatch-revisions.

**Changes:**
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` clamped (not rejected); non-integer → `ERR_VALIDATION` — core.py:169-191
- §2.7 Logical Clock — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` use real wall-clock, not the logical clock — store.py:96-108 / core.py:31-32
- §3.4 Scheduling — insert — ambiguity — `ERR_STALE_VERSION` check ordering: after qualification+statutory gates, before per-date checks — routes.py:337-348
- §3.4 Scheduling — revise — ambiguity — reschedule after any insertion published → `ERR_INVALID_STATE` (409) — routes.py:328-330
- §3.5 Fulfilment — revise — ambiguity — `line_count_actual` integer ≥ 1 else `ERR_VALIDATION` (400) — routes.py:489-491
- §3.7 Balances — revise — mismatch — `outstanding_balance_cents` sums `total_cents` across ISSUED **and PAID** minus all payments (fully-paid nets to 0; only VOID excluded) — domain.py:279-296
- §3.8 Archive/listing — insert — mismatch — both insertion list endpoints order by `scheduled_date` asc (ties by creation order), departing from §2.3 `created_at` default — routes.py:377,478
- §4 Endpoints — insert — mismatch — `POST /notices/{id}/schedule` returns HTTP 201 on initial+reschedule (sole exception to transition→200) — routes.py:369

**Aggregate resolution:** original PRD prose on `outstanding_balance` was internally inconsistent (literal reading yields negative for a paid invoice); pinned the impl's closed form (PAID totals included, fully-paid nets to 0).

## Pipeline complete — 2026-07-05T00:00:00.000Z

All steps done. Final state: 61/61 tests pass across all 8 stability rounds. Deliverables: SCAFFOLD.yaml (+DIFFICULTY/CORNER), workspace/PRD.md, workspace/PRD_COMPLETED.md, test_helpers/, test_suite/ (61 tests), workspace/implementation/ (34 endpoints, Flask in-memory).
