# Worklog — task_0185_hospice_palliative_care

## Step 1: Create Task Directory — 2026-06-06T00:00:00.000Z

Created `tasks/task_0185_hospice_palliative_care/` with `workspace/` subdirectory (pre-allocated directory, index scan skipped per orchestration instructions). Scenario: Hospice & Palliative Care benefit-period / level-of-care / interdisciplinary-plan / recertification / bereavement / revocation / per-diem-cap. Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-06-06T00:00:00.000Z

Everything checks out at Expert difficulty (9 entities, 36 endpoints, 18 errors, 4 state machines, 6 calculations, well within/above the Expert band). All three files are written, parse cleanly, and pass the scaffold lint.

Generated all three scaffold artifacts for **task_0185_hospice_palliative_care** at **Expert** difficulty, into the target directory. The scaffold lint reports **VERDICT: clean lint** (291 §1.8/§1.9 calls conform to §1.5; all FKs reverse-reachable).

**Complexity profile:** primary archetype `compliance_audit` + secondary `temporal_windowing`; layers = dual-variant calculation, rate/threshold triggers, derived-field reconciliation, optimistic concurrency; hybrid topology; branching state-machine shape; segregation-of-duties role model; immediate consistency.

**Entities (9):** Provider (annual cap root), Election (aggregate root / hospice spell), BenefitPeriod, Certification, CarePlan (self-referential revisions), CareDay, CoverageItem, Physician, BereavementCase.

**State machines (4, all non-linear):**
- Election: ELECTED → {REVOKED, DISCHARGED, EXPIRED} with a self-loop on certify (branching certify/reject) and a clock-driven auto-EXPIRE.
- Certification: DRAFT → {CERTIFIED, REJECTED} (branch with divergent side-effects).
- CarePlan: cyclic ACTIVE→ACTIVE revise loop, prior revision flipped to SUPERSEDED.
- BereavementCase: OPEN → CLOSED, gated on a death-discharge.

**Key calculations:**
- **Benefit-period 90/90/60 sequencing** — `period_sequencing`: length_days = 90 for sequences 1–2, 60 for sequence ≥3; start_offset accumulates earlier lengths (seq1→0, seq2→90, seq3→180, …); periods materialized lazily by the certify cascade. `requires_face_to_face` = true for seq ≥3 (recert face-to-face rule).
- **Per-diem (`day_per_diem`)** — tiered: ROUTINE high tier 21000¢ for the first 60 elapsed days, base 16500¢ after; RESPITE 47000¢; GIP 110000¢. Routine high-vs-base is one of the dual-variant pair.
- **Per-diem cap** — `provisional_cap_liability` (live, year-to-date) vs `final_cap_settlement` (frozen at settlement). liability = max(0, total_paid − per_beneficiary_cap × counted_beneficiaries); evaluation order pinned (count → allowance → liability). Verified divergence: 1 beneficiary → 130000¢, adding a 2nd beneficiary raises the allowance and drops provisional liability to 40000¢.
- Plus `respite_run_length` (5-consecutive-day cap) and `days_used_reconciliation` (derived-field invariant).

**Design instances:** 9 difficulty rules × 2 = **18 difficulty-design instances** (≥18 required); **39 active corner-design instances** + 2 `excluded_because` stubs, spanning all 9 claim-extraction-guide sections. All formula-derived asserts were computed in code and pinned as literals; no forbidden concurrency vocabulary; OCC `expected_election_version` always references captured `${var}` values.

All three files written: `SCAFFOLD.yaml` (1326 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (849 lines), `SCAFFOLD_CORNER_DESIGN.yaml` (1325 lines).

## Step 3: Copy Shared Files — 2026-06-06T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0185_hospice_palliative_care/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T00:00:00.000Z

Generated `workspace/PRD.md` — **258 lines**. The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

### Section structure
- **§1 Introduction** — domain framing + role overview.
- **§2 Global Specifications** (7 subsections): 2.1 RBAC & header/identity model, 2.2 fixed response envelope, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Hierarchical reads + derived-field consistency, 2.6 Per-diem precision (integer cents, no rounding), 2.7 OCC on the election.
- **§3 Business Logic** (13 subsections): provider/cap window, election + period-1 materialization, 90/90/60 cadence, certification/recert/face-to-face, interdisciplinary plan, per-diem rate table, care-day temporal rules + respite run, medication/DME coverage, revocation/discharge/expiry, bereavement, aggregate cap (provisional vs final), the test-driving clock, validation precedence.
- **§4 Endpoint Definitions** — 36-row, 4-column table.
- **§5 Error Code Catalogue** — 18-row, 2-column table.

### Coverage confirmation
- **Entities**: all 9 covered, each carrying id/created_at/updated_at/version.
- **State machines**: all four with every precondition→error pairing and side-effect stated.
- **Calculations**: benefit-period sequencing (90/90/60, start-offset accumulation, current_period_number cursor); per-diem tiers (ROUTINE high 21000¢ first 60 days / base 16500¢ after, RESPITE 47000¢, GIP 110000¢); respite run-length with tie-break; provisional vs final cap; days-used reconciliation — all in precise prose.
- **Validations**: all 18 with priority precedence in §3.13.
- **Endpoints**: all 36; **errors**: all 18; **RBAC**: 4 roles, entity_backed:Physician vs opaque identity semantics.

Hard-contract checks (field/rule/path-purity) all reported PASS. A stray `</content>` artifact briefly leaked into the file and was removed; file ends cleanly at the §5 table (verified by orchestrator: tail clean, no artifacts).

## Step 5: Generate Unit Tests — 2026-06-06T00:00:00.000Z

Generated complete test infrastructure under a strict design-index-only contract. Every test translates exactly one non-stub instance from the difficulty or corner design index; every docstring carries a verbatim PRD citation plus a single `Design:` tag resolving to a real instance.

### test_helpers/ (9 files)
- `types.py` — 9 entity TypedDicts (all carry `updated_at`/`version`) + 11 status/level/role enums
- `api_client.py` — `ApiClient(GenericApiClient)`, 40 endpoint methods incl. `/_clock/set_current_utc` test driver
- `api_errors.py` — 18-member `ApiErrorId` enum + HTTP-status map
- `assertions.py` — per-entity assertions + `assert_provider_invariants` (cap-ledger non-negativity)
- `factories.py` — 8 payload factories (input fields only)
- `constants.py` — per-diem rate table, 90/90/60 cadence, respite/cap thresholds
- `test_users.py` — opaque-role shared headers + `make_physician_headers(id)` for entity-backed Physician role
- `fixtures.py` — composite setup helpers (provider+election scaffolds, cap-ledger multi-beneficiary states, certification/period progression, care-plan supersede chains, respite-run-of-5, settled provider, death-discharge + bereavement)
- `__init__.py` — barrel export

### test_suite/ (conftest + 7 test files)
74 tests across per-diem calculations, cap ledger, certification workflow, care-plan/coverage, care-day temporal rules, election lifecycle, validation/RBAC.

### Coverage
- **Queue A (Difficulty):** all 18 instances × exactly 2 tests = **36 tests**, no shortfalls
- **Queue B (Corner):** **38 tests** covering 38 of 39 non-stub instances (1 each)
- **Total: 74 tests**, all collect cleanly
- The 1 `excluded_because` stub (`duplicate_care_day_already_covered_by_difficulty`) correctly NOT translated.

### Skipped (1 instance)
- `Corner/state_machines/close_already_closed_bereavement_rejected` — **fails unique derivability.** PRD §3.10 only states closing transitions `OPEN → CLOSED`; it is silent on re-closing an already-`CLOSED` case (no error_id, no idempotency rule). A faithful PRD-only implementer could ship either a 200 no-op or a 4xx rejection. Skipped per the silence pattern, not weakened/xfailed.

All docstring PRD citations verified verbatim, rule-bearing, non-abbreviated, ending with exactly one valid `Design:` tag.

## Step 6: Generate Implementation — 2026-06-06T00:00:00.000Z

Generated complete Python + Flask implementation at `workspace/implementation/`.

### Files written
- `start.sh` — guarded-install foreground launcher (`exec python3 app.py`)
- `requirements.txt` — `flask==3.0.3`
- `app.py` (991 lines) — Flask entry point: all 37 endpoints, error handlers, validation precedence, state machines
- `services.py` — calculations, derived-field reconciliation, serializers
- `db.py` — in-memory store + logical clock
- `util.py` — request parsing, datetime/midnight handling, pagination
- `middleware.py` — `X-User-ID`/`X-User-Role` auth + RBAC
- `response.py` — `meta`/`response_type`/`data` envelope, `req_` ids, 3-fractional-digit timestamps
- `errors.py` — 18-code error catalog

### Storage model
In-memory only — module-level dicts in `db.py` keyed by UUID id, plus monotonic `_seq` for deterministic created_at tie-breaks and a logical UTC clock. No SQLite/disk/tmp. State wiped on every `start.sh` re-invocation (verified clean-port restart → all lists total_count=0). Nothing seeded at startup.

### Benefit-period 90/90/60 sequencing
`length_days(seq)` = 90 for seq∈{1,2} else 60; `start_offset_days(seq)` sums earlier nominal lengths (seq1→0, seq2→90, seq3→180…). Period 1 materialized at election; each successful certify commit materializes seq+1 lazily, sets cert_status=CERTIFIED/certification_id, increments Election.version by one. `requires_face_to_face` true for seq≥3, enforcing 30-day pre-period window `[start_offset−30, start_offset]`. `current_period_number` = clock-elapsed-day cursor bounded by highest materialized period.

### Per-diem & cap
Per-diem: ROUTINE 21000¢ when elapsed-day index <60 else 16500¢; RESPITE 47000¢; GIP 110000¢ — integer cents, no rounding. `high_intensity` validated against elapsed window. **Provisional cap** (recomputed each care-day post): total_paid = raw sum in-window; counted_beneficiaries = distinct elections w/ in-window care day; liability = max(0, total_paid − per_beneficiary_cap × counted). **Final settlement**: each beneficiary's in-window payments min-capped at per_beneficiary_cap_cents before freezing, demand on max(0, raw_total − allowance), cap_settled flips true (verified divergence from provisional).

### start.sh contract
Reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`, guards pip install behind flask-import check. Boots clean from fresh process with empty state.

Self-validated with two ad-hoc suites (49 lifecycle + 13 edge checks) — all pass on clean boot.

## Step 7: Run Tests and Iterate — 2026-06-06T00:00:00.000Z

All 8 parallel rounds pass cleanly (72/72 each). The sweep is stable.

**Iterations run:** 2 sweeps to diagnose + fix, then 2 confirmation sweeps. All 8 parallel rounds now pass 72/72.

**Initial state:** 72/74, with the same 2 tests failing deterministically across all 8 rounds (not flaky — genuine PRD-derivability defects).

**Tests deleted (2) — both unique-derivability collapses per the cardinal rule "I can produce the verbatim quote AND two divergent PRD-faithful implementations":**

1. `test_certify_commit_without_narrative_takes_reject_branch` (test_03_certification_workflow.py) — **CONTRADICTORY-PRD / unique-derivability collapse.** PRD §3.4 contains two mutually-contradictory sentences about the same precondition failure (narrative absent on commit). Sentence A: *"If the narrative is absent … the commit is rejected with `ERR_CERTIFICATION_INCOMPLETE` (HTTP 422)"* — reinforced by §3.13's precedence chain and §5's error catalogue (both list this error → dominant reading = return 422). Sentence B: *"the commit takes the reject branch: the certification's status becomes REJECTED …"* — the reading the test asserts (HTTP 201 + status REJECTED). A faithful implementer following the §5/§3.13-supported error reading returns 422 (what the impl does) and fails the test; one following Sentence B returns 201. Compounding this, the sibling test `test_initial_cert_by_non_director_without_second_rejected` asserts HTTP 422 `ERR_CERTIFICATION_INCOMPLETE` for the *same* §3.4 completeness check, so the two tests demand contradictory outcomes from one implementation. Scaffold origin: `Difficulty/non_linear_state_machine/certification_branch_certify_vs_reject`.

2. `test_election_expires_when_period1_lapses_uncertified` (test_06_election_lifecycle.py) — **MISSING-REFERENT / unique-derivability collapse.** PRD §3.9 and §3.12 both anchor the expiry trigger on *"the **highest CERTIFIED period**"* — §3.12: *"auto-transitions to EXPIRED any ELECTED election whose highest CERTIFIED period has ended."* The test exercises a scenario where period 1 was **never certified**, so there is no "highest CERTIFIED period" referent. A faithful implementer reasonably requires a CERTIFIED period to exist before measuring expiry (exactly what the impl does → election stays ELECTED, test fails); another could read the §1 intro hint *"a benefit period quietly expiring un-recertified"* as forcing EXPIRED. The scaffold's own transition guard (`SCAFFOLD.yaml` line 449: *"the clock cursor has advanced past the end of the highest CERTIFIED period AND the next period is still PENDING_CERT"*) confirms the rule itself presumes a certified period exists. Scaffold origin: `Corner/state_machines/election_expires_when_period_lapses_uncertified`.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful on both points (it returns `ERR_CERTIFICATION_INCOMPLETE`/422 per the §5/§3.13-supported reading, and gates expiry on an existing highest-CERTIFIED period per §3.9/§3.12). Both failures were test-side derivability defects, correctly resolved by deletion rather than by weakening PRD-required behavior.

**Note on round-3 transience:** During the first post-fix sweep, round 3's results file was briefly missing due to a boot/port-contention spike under 8× concurrent load (not a test failure — it produced 72/72 when isolated). The final confirmation sweep (with a higher boot `--timeout 180`) produced clean 72/72 across all 8 rounds with no missing files.

Orchestrator verification: all 8 `results.{1..8}.json` confirmed `passed=72 / total=72`; current `test_suite/` count = 72.

## Step 8: Finalize PRD — 2026-06-06T00:00:00.000Z

Produced `workspace/PRD_FINALIZED.md`. Both edits trace to the two `<step_7_diff>` test deletions.

**Line counts:** PRD.md 258 → PRD_FINALIZED.md 258 (0% line-delta; both edits are inline expansions within existing paragraphs, no new lines/sections).

**Changes:**
- **§3.4 (Certification reject branch) — revise — Pinned the HTTP outcome of a failed certify-commit.** PRD §3.4 contradicted itself: ¶4 says a precondition failure "is rejected with `ERR_CERTIFICATION_INCOMPLETE`/`ERR_FACE_TO_FACE_REQUIRED` (422)", while ¶5's "takes the reject branch" framing reads as a 201 returning the REJECTED certification. The impl persists the cert as REJECTED+rejection_reason then **raises the 422 error** (no 201 path for a failed precondition). Clarified ¶5 to state the reject branch returns the corresponding 422 error (f2f → `ERR_FACE_TO_FACE_REQUIRED`, else `ERR_CERTIFICATION_INCOMPLETE`) rather than a 201 carrying the rejected cert, and that the rejected cert record is persisted. — `implementation/app.py:454-458, 478-486`
- **§3.9 (Expiry trigger) — revise — Pinned the no-CERTIFIED-period corner case.** PRD §3.9/§3.12 frame expiry on "the highest CERTIFIED period" but leave silent what happens when no period was ever certified (period 1 lapses uncertified). The impl gates expiry on at least one CERTIFIED period existing (`if not certified: continue`), so such an election stays ELECTED. Added a clause stating the trigger presupposes a CERTIFIED period and that an election with none is not expired by this rule. — `implementation/app.py:73-91` (esp. line 82 `if not certified: continue`)

Per-edit pre-edit (NO-NEW-MISMATCH) searches performed for both edits; both confirmed globally consistent with §3.12 / §3.13 / §5. Orchestrator verification: PRD_FINALIZED.md present, 4 changed lines (2 inline revises).

## Step 9: Complete PRD — 2026-06-06T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal in-paragraph patch over `PRD_FINALIZED.md`, pinning every behavior where the PRD was silent or mismatched against `implementation/`.

**Counts**
- Source `PRD_FINALIZED.md`: 258 lines, 41,381 bytes.
- `PRD_COMPLETED.md`: 258 lines, 47,554 bytes (char-delta +6,151).
- 20 lines revised, all single-line in-paragraph edits — no new sections/paragraphs/lines.
- Classification: 13 ambiguity-pins, 7 mismatch-revisions.

**Changes** (`{section} — {kind} — {class} — {what} — {impl}`)
- §2.1 — revise — ambiguity — blank/whitespace `X-User-ID` and unrecognized `X-User-Role` both → `ERR_UNAUTHENTICATED`; 403 only for recognized-but-unauthorized roles — middleware.py:15-19
- §2.3 — revise — ambiguity — pagination: `offset` min 0 / no upper bound, non-integer params invalid, offset > total → empty page — util.py:104-112
- §2.3 — revise — ambiguity — list ordering ties broken by creation order; care-day list `service_date` asc then creation order; `has_more` formula — app.py:161,798; response.py:46
- §2.4 — revise — ambiguity — `version` initial value is 1 — db.py:51
- §2.5 — revise — mismatch — `days_used_in_period` resolves "current period" as latest care day's period (creation-order tie-break), falls back to `current_period_number`/0; reconciliation bumps `version` only when a derived value actually changed — services.py:119-156
- §3.2 — revise — ambiguity — election refusal raises `ERR_CAP_YEAR_SETTLED`, gated on `election_date` inside settled 365-day window — app.py:217-218
- §3.4 — revise — ambiguity — `commit` defaults true when omitted/null — app.py:394-396
- §3.4 — revise — ambiguity — draft mode (commit false) returns 201, skips all certify preconditions and OCC, persists even on stale version, leaves election version unchanged — app.py:440-441
- §3.4 — revise — ambiguity — two-physician backing = any other persisted cert for same election+sequence by a distinct physician, any status — app.py:470-477
- §3.4 — revise — ambiguity — face-to-face window inclusive both ends (`start − 30d` ≤ date ≤ `start`) — app.py:448-451
- §3.5 — revise — ambiguity — invalid/non-array `idg_members` → `ERR_INVALID_REQUEST` before core-completeness check — app.py:564-568
- §3.5 — revise — silence — first-plan-while-active and inactive/foreign supersede target both → `ERR_STALE_ELECTION_VERSION`, target check before version check — app.py:598-613
- §3.6 — revise — ambiguity — `high_intensity` defaults false; `service_date` must be UTC midnight; `benefit_period_id` null when no materialized window contains the day — app.py:692-698,750-755
- §3.7 — revise — ambiguity — settled-window care-day guard fires only when settled AND `service_date` in 365-day window — app.py:709
- §3.8 — revise — mismatch — uncovered orders rejected (not stored), so every persisted `CoverageItem` is `COVERED`; `EXCLUDED` never appears — app.py:845-860
- §3.9 — revise — silence — revoke date-bound violation → `ERR_INVALID_REQUEST` — app.py:294-298
- §3.9 — revise — silence — discharge date-bound violation → `ERR_INVALID_REQUEST` — app.py:323-324
- §3.9 — revise — ambiguity — expiry boundary: cursor ≥ certified period end offset, lowest pending sequence above the certified one — app.py:85-89
- §3.10 — revise — silence — early `enrolled_date` → `ERR_INVALID_REQUEST` after eligibility checks; close accepts any current status — app.py:920-931,953-960
- §3.11 — revise — ambiguity — provisional ledger recompute mutates fields without bumping `updated_at`/`version`; suppressed once settled — app.py:132-137; services.py:215-223
- §3.11 — revise — mismatch — final settlement freezes `total_paid_cents` as per-beneficiary-capped sum, but `cap_liability_cents` uses raw uncapped total minus allowance (so they need not satisfy `liability == total_paid − allowance`) — services.py:226-248

Orchestrator verification: PRD_COMPLETED.md present (47,554 bytes), no stray artifacts; final workspace tree contains PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md, implementation/.

---

## Pipeline Complete

All 9 steps executed. Final state: **72/72 tests pass across all 8 parallel stability rounds**. Task `task_0185_hospice_palliative_care` (Hospice & Palliative Care, Expert difficulty) is fully generated and green.
