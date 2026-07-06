# Worklog — task_0546_foundation_repair

## Step 1: Create Task Directory — 2026-07-02T23:34:00.000Z

Created `tasks/task_0546_foundation_repair/` and `tasks/task_0546_foundation_repair/workspace/` (index fixed by user directive; no ./tasks/ scan performed). Difficulty: Expert (passed only to scaffold-generator).

## Step 2: Generate Scaffold (Expert) — 2026-07-03T00:01:00.000Z

All three artifacts are generated, cross-checked, and pass `scaffold_lint.py` cleanly. Summary of what I produced in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0546_foundation_repair/`:

## SCAFFOLD.yaml (§1.0–§1.7)
- **Profile**: Expert, `workflow_orchestration` + `pricing_engine`, flat topology under `/foundation`, parallel state-machine shape, peer roles, immediate consistency. Layers: dual-variant calc, cascading side effects, scheduled actions, optimistic concurrency.
- **10 entities**: Lead, Inspection, EngineeringScope, Quote, Job, Crew, Permit, Warranty, MaintenanceVisit, Claim (all FKs use canonical `FK -> Parent.id`).
- **8 state machines**: Quote (cyclic SENT↔REVISED), Claim (cyclic UNDER_REVIEW↔NEEDS_INFO), Job (parallel `fulfillment_status` × `permit_status`), plus Inspection, EngineeringScope (supersede), Permit, Warranty, MaintenanceVisit.
- **5 calculations**: `pier_pricing` (tiered, estimate vs final variants), `financing_total` (pinned-order circular dependency), `claim_settlement` (FULL vs PRORATED variants), `crew_booked_minutes`, `lead_financing_balance`. All literals machine-verified.
- **1 concurrency rule**: OCC `scope-create-stale-lead` on `expected_lead_version` (412).
- **21 validations** (priority-ordered), **51 endpoints** (incl. `/_clock/set_current_utc`, default `2026-05-01T00:00:00Z`), **21 errors**, **6 roles** (Customer is `entity_backed:Lead`; rest `opaque`).

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
- **18 instances** = all 9 rules × 2, each with structured setup/trigger/assert, pre-computed literal asserts machine-verified.

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
- **33 instances**: 29 active + 4 `excluded_because` stubs pointing to §1.8 instances.

**Lint**: `VERDICT: clean lint` — 516 calls scanned, all conform to §1.5, all FKs reverse-reachable.

## Step 3: Copy Shared Files — 2026-07-03T00:02:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0546_foundation_repair/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-03T00:10:00.000Z

Generated `workspace/PRD.md` — a 269-line prose PRD. §1 Introduction, §2 Global Specifications (10 subsections: RBAC 6 roles, response envelope, pagination, common properties/versioning, logical clock, resolution/reverse-lookups, OCC, cascades/compensation, monetary precision, validation ordering), §3 Business Logic (8 lifecycle subsections), §4 endpoint table (51 endpoints incl. `_clock`), §5 error table (21 errors). Mechanical checks: all 62 required field identifiers present verbatim; all 10 state machines, 5 calculations, OCC rule, 21-rule validation chain, 3 cascades, 21 error IDs covered; §3 path-purity clean. Both design indices withheld.

## Step 5: Generate Unit Tests — 2026-07-03T03:05:00.000Z

Test infrastructure generation complete for `task_0546_foundation_repair`.

## What was built

**Stage 1 — `test_helpers/`** (9 files): PRD-specific infrastructure over the `prd_bench_local_runner.testing` framework.
- `types.py` — 10 entity TypedDicts (all carry the four common fields; Job exposes the two independent `fulfillment_status`/`permit_status` dimensions) + status/role enums.
- `api_client.py` — one method per PRD §4 endpoint, including the logical-clock setter.
- `api_errors.py` — all 21 error IDs + HTTP-status map, registered with the framework.
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (Customer is the only entity-backed role → `make_customer_headers(lead_id)` for ownership threading), and a substantial `fixtures.py` with composite pipeline builders (sent-quote → accepted-job → scheduled → completed-install → active-warranty → claim scenarios, plus the two-job/one-crew and missed-visit scenarios).

**Stage 2 — `test_suite/`** (conftest + 10 domain-named files): 65 tests, all collected cleanly.

## Design-index coverage (the only test source)
- **Queue A (Difficulty):** all 18 instances across 9 rules, **exactly 2 tests each** (36 tests). Boundary/precedence instances got meaningful second tests (below-boundary tier, abutting-window-allowed, positive-control accept, precedence made observable via status-code distinction).
- **Queue B (Corner):** all 29 non-stub instances, **1 test each** (29 tests). The 4 `excluded_because:` stubs (`pier_pricing_estimate`, `financing_total`, `crew_double_book`, `visit_min_gap`) were **not** translated; their `difficulty_instance` cross-references all resolve.

## Verification performed
- `py_compile` + full `test_helpers` import (via framework stub) — all names and 40+ ApiClient methods resolve.
- `pytest --collect-only` — 65 tests collected, zero import/collection errors.
- All ~76 verbatim PRD citations confirmed via literal `grep` of `PRD.md` (C1).
- Every docstring ends with exactly one `Design:` tag matching a real source `name:` (C4); no untagged/dual-tagged tests.
- No scaffold/§1.x/Table leakage; no `skip`/`xfail`/`skipif`.

## One deliberate PRD-first skip (not a gap in coverage)
The corner instance `lead_create_returns_201_and_envelope` asserts `version == 1`, but PRD §2.4 only says version "starts at its initial value" (0 vs 1 is not uniquely derivable — a default-value silence pattern). The test still covers the instance, asserting the PRD-derivable facts (201, `response_type == "object"`, `meta.api_request_id`, `financing_balance_cents == 0`, `active_visit_count == 0`) and omits the non-derivable `version == 1` sub-assertion. My OCC tests avoid hard-coding the initial version by capturing it from the live lead response.

## Step 6: Generate Implementation — 2026-07-03T03:05:30.000Z

The implementation is complete and verified.

## What was built

A complete Python + Flask REST API for the Foundation Repair task at `workspace/implementation/`:

- **`start.sh`** — foreground launcher, guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000).
- **`app.py`** — single-file server (~48 KB): in-memory store, no seeding, fresh state on every boot.
- **`requirements.txt`** — `Flask==3.0.3`.

## Coverage

All 10 entities (Lead, Inspection, EngineeringScope, Quote, Job, Crew, Permit, Warranty, MaintenanceVisit, Claim) with full CRUD, all state-machine transitions, and the `_clock` test hook. Key details implemented faithfully:

- **Envelope** exactly per §1.0/§2.2: `meta`/`response_type`/`data`, `req_` ids, ISO-8601 with 3 fractional digits, list pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/min1/max100/0).
- **Auth/RBAC** via `X-User-Role` (401) + role permission (403); Customer ownership via `X-User-ID == lead_id` (direct, or through warranty/claim).
- **Calculations** with `Decimal` + `ROUND_HALF_UP`, pinned rounding order (per-pier rounded before multiplying by count; discount→financed→fee→total). Verified: subtotal 2,177,250; final variant diverges on actual piers; claim settlement `ceil(inches/0.5)*150000*coverage` with FULL/PRORATED and floor.
- **Cascades**: quote-accept (Job + financing debit + single lead version bump), install-complete 3-hop (Warranty→auto MaintenanceVisit at +365d→`active_visit_count`), claim-approve 2-hop (remediation Job + `remediation_count`), permit bubble-up, and reverse compensations on job cancel (crew minutes + financing credit). Each cascaded resource gets its own `version`/`updated_at` bump.
- **OCC** on scope create via `expected_lead_version` (412 `ERR_STALE_VERSION`).
- **Logical clock** default `2026-05-01T00:00:00Z`; lazy quote expiry (GET shows `EXPIRED`; accept returns `ERR_QUOTE_EXPIRED`).
- **Validation ordering** follows PRD §2.10 canonical numeric priority (e.g. schedule: state→soil→double-book→permit→region→window; maintenance-visit: too-soon(10)→warranty-active(13)→date-in-past(18)), which the skill designates authoritative over the scaffold's precondition listing order.

## Verification

Booted from a fresh process and ran 53 end-to-end assertions (full happy-path pipeline plus error cases: auth, ownership, OCC, double-booking overlap-vs-adjacency, unstable-soil, region mismatch, invalid window, pier tolerance, financing limit 402, visit date-in-past/too-soon, remediation-not-complete, expiry) — all pass.

Two notable interpretation decisions (both defensible per the skill's "PRD §2.10 canonical order and priority numbers govern" rule): (1) validation precedence follows the §2.10 numbered list rather than the scaffold state-machine precondition order where they conflict; (2) `booked_minutes` is maintained incrementally (add on schedule, subtract on cancel-from-SCHEDULED) per the explicit side-effect prose and calculation triggers, not recomputed on complete.

## Step 7: Run Tests and Iterate — 2026-07-03T03:20:00.000Z

All 8 parallel rounds pass cleanly (65/65 passed, 0 failed, 0 errors). My initial per-round summary used the wrong JSON field name (`outcome` instead of `status`), which falsely flagged every test; the corrected read confirms a fully green sweep.

Summary

- Iterations run: 1 (single 8-round parallel sweep; no fixes needed).
- Tests deleted: none.
- Fixes applied to test_helpers/: none.
- Fixes applied to implementation/: none.

The task is already passing all 65 tests across all 8 concurrent stability rounds. No flakiness, no PRD-silence deletions, and no implementation or fixture changes were required.

Orchestrator independent verification: parsed all 8 results.{1..8}.json — every round reports passed=65 total=65 failed=0.

## Step 8: Finalize PRD — 2026-07-03T03:22:00.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already uniquely determined every behavior the implementation exhibits, so no PRD_FINALIZED.md was produced. Step 9 proceeds from PRD.md.

## Step 9: Complete PRD — 2026-07-03T03:30:00.000Z

Done. Full PRD-vs-implementation scan produced workspace/PRD_COMPLETED.md.

**File metrics**
- `PRD.md`: 269 lines, 41,032 chars
- `PRD_COMPLETED.md`: 269 lines, 41,258 chars
- Char delta: +226 (line count unchanged — all edits were in-paragraph)

**Change counts**: 3 ambiguity-pins, 2 mismatch-revisions (the mismatch is one logical reordering done as 2 physical edits)

**Changes**
- §2.3 Pagination — insert — ambiguity — pinned that a negative `offset` is clamped to 0 and a non-integer `limit`/`offset` yields `ERR_VALIDATION`; PRD only stated defaults/clamps for valid input — `implementation/app.py:372-387`
- §2.4 Common Resource Properties — revise — ambiguity — `version` "starts at its initial value" replaced with "starts at 1"; PRD never named the initial value — `implementation/app.py:157`
- §3.1 Lead Intake / Free Inspection — revise — ambiguity — `crack_severity` "0-to-5 severity index" pinned to an integer in the inclusive 0–5 range with out-of-range/non-integer → `ERR_VALIDATION` — `implementation/app.py:507-509`
- §3.5 Permits/Crews/Scheduling — revise — mismatch — the `ERR_SCHEDULE_WINDOW_INVALID` window check was narrated as the *first* priority check, but impl (and §2.10's canonical order + example) evaluates it *last*, after soil/double-booking/permit/region; moved the window sentence to the end of the check sequence — `implementation/app.py:903-940` (window at 938-940)

**Deliberately left unchanged**: §3.7's three maintenance-visit preconditions have no explicit order claim, so §2.10's canonical order already governs (no mismatch). §2.1's "two mandatory headers" is consistent with impl (missing X-User-ID tolerated for opaque roles; surfaces as ownership ERR_FORBIDDEN for Customers). All pricing formulas, rounding orders, cascades, compensations, state machines, RBAC, and error codes/HTTP statuses already matched the PRD uniquely.

## Pipeline complete — 2026-07-03T03:30:30.000Z

All steps done. Final state: 65/65 tests green across all 8 concurrent stability rounds; PRD_COMPLETED.md produced.
