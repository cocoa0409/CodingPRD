# Worklog — task_1096_travel_nurse_locum_tenens

Scenario: Travel-Nurse & Locum-Tenens Agency: clinician & specialty/license (compact), assignment & contract (13-week), housing/stipend & GSA per-diem, credentialing & compliance packet, timesheet & bill/pay-margin, extension & cancellation, multi-state licensing, payroll/1099

Difficulty: Expert

## Step 1: Create task directory — 2026-07-24T02:59:00.000Z

Pre-assigned folder used as-is: `tasks/task_1096_travel_nurse_locum_tenens/` with `workspace/`. Directory scan skipped per instruction.

## Step 3: Copy shared files — 2026-07-24T02:59:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1096_travel_nurse_locum_tenens/workspace/INSTRUCTION.md` (done early; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-07-24T03:47:00.000Z

All three files are complete, pass `yaml.safe_load`, pass the scaffold linter clean, and pass my own cross-reference audits (grounds resolution, name uniqueness, error coverage, forbidden-vocab, undeclared-constant, `excluded_because` back-references).

Generated a fresh **Expert** scaffold for the Travel-Nurse & Locum-Tenens Agency scenario, purely from the scenario text and the skill spec (no sibling tasks consulted).

**Files:**
- `SCAFFOLD.yaml` — 2323 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2141 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2624 lines

**Scaffold surface:**
- Entities: 12 (Clinician, License, Facility, PerDiemLocality, Assignment, Contract, CredentialPacket, CredentialItem, Timesheet, EarningsStatement, PayrollRun, ExtensionRequest)
- Endpoints: 32 (incl. `/_clock/set_current_utc`; default clock 2026-05-01T00:00:00Z)
- State machines: 10 (Assignment has two parallel dimensions `staffing_status` × `compliance_status`; Contract/CredentialPacket/Timesheet/ExtensionRequest are cyclic)
- Calculations: 12 (per-line-then-sum rounding pinned; margin-floor uplift as circular-looking dependency resolved with exact integer `ceil_div(cost*100, 78)`; dual variants on stipend accrual and packet readiness)
- Validations: 21 (priority-ordered), Errors: 32, Roles: 6 (segregation-of-duties)
- Concurrency rules: 2 (OCC on Assignment.version and Contract.version)

**Design coverage:** §1.8: 9 rules × 2 instances = 18. §1.9: 54 instances (33 full recipes + 21 excluded stubs). Linter verdict: clean lint. Scaffold subagent id: af898540e74eb0618.

## Step 4: Generate PRD — 2026-07-24T03:56:00.000Z

Generated `workspace/PRD.md` (313 lines; 5 top-level sections, 19 subsections) for the Travel-Nurse & Locum-Tenens Agency API (12 entities, parallel two-dimension Assignment state machine, 10 calcs with dual-variant logic, 21 priority-ordered validations, 32 endpoints, 32 errors, 6 SoD roles).

Hard-contract verification: Contract 1 Field-Name Coverage PASS (117 identifiers, 0 missing). Contract 2 Rule Coverage: all 10 calcs rendered (per-line rounding order, max(daily,weekly) OT, dual-variant stipend, ceil_div(cost*100,78) margin uplift, dual-basis readiness, license coverage ranking, cancellation waterfall, payroll claim); both OCC rules; 3 SoD variants; cascades A+B; validation priority in §2.8. Contract 3 §3 Path Purity PASS. All 22 declared constants present. All 32 error IDs in prose. PRD subagent id: a0f7c6f30dac1dd1c.

## Steps 5 & 6: Tests + Implementation (pre-existing on disk) — 2026-07-24T04:22:00.000Z

RESUMED session: Steps 5 (test_helpers/ + test_suite/ — 12 test modules, 80 test functions, conftest.py) and 6 (workspace/implementation/ — app.py + start.sh + 8 py modules) were generated in a prior session; worklog entries were not recorded then. Files validated on resume: py_compile clean; boots in 2s; **route count 32 == scaffold endpoint count 32** (partial-write guard PASS). Proceeding to Step 7.

## Step 7: Stability sweep — RESUME START 2026-07-24T11:18:00.000Z

Sweep configured as 4 WAVES OF 2 rounds (host shared with 4 sibling Step-7 sweeps) via `sweep.sh`. Long-lived diagnostic subagent owns the run→diagnose→fix loop.

## Step 7: Stability sweep — COMPLETE 2026-07-24T11:40:00.000Z

Orchestrator independently re-parsed all 8 results files: rounds 1–8 each passed=80/total=80, breakdown {'passed':80}, zero skip/xfail/error strings. CLEAN GREEN.

Subagent summary (verbatim):

- **Iterations run:** 3 (initial sweep + 2 fix-and-resweep cycles)
- **Final sweep:** all 8 rounds passed==total = 80/80, 0 skip/xfail/error.
- **Tests deleted:** none. (One assertion within a kept test was removed — see test_suite fixes.)
- **test_helpers/ fixes:**
  - `test_helpers/fixtures.py` — `Ctx` container — `Ctx(dict)` with `__getattr__ = dict.get` let `ctx.items` resolve to the built-in `dict.items` method (since `__getattr__` only fires on lookup *failure*), never the stored `"items"` key, raising `TypeError: 'builtin_function_or_method' object is not subscriptable` in 4 tests. Fixed by mirroring stored keys into the instance `__dict__` so attribute access shadows the class method.
- **test_suite/ fixes:**
  - `test_suite/test_02_placement_and_licensure.py` — `test_assignment_create_populates_projection_and_child_resources` — test asserted `projected_pay_cost_cents == 4967716` (which requires a per-diem stipend) but never seeded a per-diem row, so the impl correctly computed stipend=0 per PRD §3.8 ("no such row → stipend 0"). Added the missing `create_per_diem(api)` setup call (other tests seed it via `provision()`); the expected value is now PRD-derivable.
  - `test_suite/test_01_reference_and_registration.py` — `test_logical_clock_defaults_then_moves` — removed the single assertion `clock["current_utc"] == "2026-08-01T12:00:00Z"` (format silence / non-unique-derivability): PRD never pins `current_utc`'s fractional-digit rendering, and §2.4 itself writes the clock instant with a bare `Z` while the general instant convention is `.mmmZ`, so both renderings are PRD-faithful. Kept all covered assertions (default-clock `created_at`, advanced `created_at == ...000Z`).
- **implementation/ fixes:**
  - `workspace/implementation/app.py` — `__main__` entry block — **critical boot bug**: launched via `python3 app.py`, the module is `__main__`, but view modules do `from app import app`, importing a *second* copy of the module named `app` and registering all routes on *that* Flask instance while `__main__` ran its own routeless instance — every route returned `ERR_VALIDATION "Unknown route"` (78/80 tests failing). Fixed the `__main__` block to run the fully-configured `app`-module instance (`import app as _appmod; _appmod.app.run(...)`).

→ Implementation was changed (app.py boot fix). Step 8 warranted.

## Step 8: Finalize PRD — 2026-07-24T11:41:00.000Z

Produced `workspace/PRD_FINALIZED.md` (313 lines, 1 line revised, ~0.3% delta).

- §2.9 (PlatformAdmin / logical clock, line 144) — revise — pinned the `current_utc` echo rendering to exactly three fractional digits (`YYYY-MM-DDTHH:MM:SS.mmmZ`) regardless of input precision; default clock echoes `2026-05-01T00:00:00.000Z`. Source: store.py:21-27,54-55 (`render_ts`/`now_ts`), returned at views_core.py:34.

Per-item verdicts: (1) Ctx fixture bug — pure harness plumbing, no PRD surface, no edit. (2) per-diem seeding — PRD §3.8 already pins "no row → stipend 0", fixture bug, no edit. (3) clock echo rendering — REAL PRD-silence, pinned. (4) app.py `__main__` launch — pure plumbing, no PRD surface, no edit. NO-NEW-MISMATCH check: all instant renderers (api_request_timestamp, created_at/updated_at, *_signed_at, resolved_at, verified_at) route through the same `.mmmZ` renderer, so "like every other instant" holds universally.

## Step 9: Complete PRD — 2026-07-24T11:46:00.000Z

Produced `workspace/PRD_COMPLETED.md` (313→314 lines, +1; chars 61,771→63,558, Δ+1,787). Full PRD-vs-implementation surface scan. 6 changes: 4 ambiguity-pins, 2 mismatch-revisions.

- §2.3 Pagination — insert — ambiguity — list-order tie-break (equal `created_at` → ascending insertion order via `_seq`) + enumerated per-endpoint equality-filter query params. common.py:267; views_assignment.py:186; views_core.py:127-133; views_credential.py:67-72; views_finance.py:112,252.
- §2.10 Reverse-reachability — insert — ambiguity — added `ERR_EARNINGS_STATEMENT_NOT_FOUND` for bad `/earnings-statements/{id}` read. views_finance.py:242.
- §5 Error Catalogue — insert — ambiguity — added `ERR_EARNINGS_STATEMENT_NOT_FOUND | 404` row. views_finance.py:242.
- §3.3 Projected economics — insert — ambiguity — projected weekly stipend uses 0 lodging/M&IE when no per-diem row effective on `start_date`. domain.py:87-89.
- §3.4 Credentialing — insert — ambiguity — item-attach / item-transition refresh packet `updated_at`/`version` ONLY when a readiness value actually changes. domain.py:274-281; views_credential.py:101,205-221.
- §3.9 Cancellation — revise — MISMATCH — finalized PRD claimed DRAFT cancel always penalty 0 / no statement; impl runs the same notice waterfall with no DRAFT special-case, so under-30-days DRAFT cancel creates a shortfall penalty statement. Revised to uniform waterfall (penalty 0 only when shortfall hours 0, i.e. ≥30 days notice). domain.py:305-367.

Non-changes verified already-pinned/unobservable: ACCEPT-extension error precedence (§2.8 governs), contract-revise `guaranteed_hours_remaining` (unobservable pre-consumption), clinician version touch-only-on-change (no-change path covered by §3.9).

## PIPELINE COMPLETE — 2026-07-24T11:46:30.000Z

Steps 7→8→9 done on resume. Step 7: 8/8 rounds green 80/80, 0 skip/xfail/error (orchestrator independently re-parsed all 8 results.N.json). Step 8: PRD_FINALIZED.md (1 edit). Step 9: PRD_COMPLETED.md (6 edits). All artifacts present: PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, results.1-8.json (8/8).


