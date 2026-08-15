# Worklog — task_1517_nonprofit_board_governance_compliance

## Step 1: Create Task Directory — 2026-08-13T18:07:00.000Z

Task directory `tasks/task_1517_nonprofit_board_governance_compliance/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Scaffold Generation — 2026-08-13T19:45:00.000Z

Generated SCAFFOLD.yaml (§1.0–§1.7: 16 entities, 14 state machines, 3 OCC concurrency rules, 12 calculations, 22 validations, 99 endpoints, 56 errors, 6 roles), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8: 24 instances across all 9 rules), SCAFFOLD_CORNER_DESIGN.yaml (§1.9: 78 instances, 73 active + 5 excluded stubs). scaffold_lint.py verdict: clean lint (1171 calls scanned). No sibling task inspected; design derived solely from the scenario description and the skill specification.

<details><summary>Full verbatim subagent summary</summary>

Scaffold generation complete. All three artifacts written and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1517_nonprofit_board_governance_compliance/SCAFFOLD.yaml` (§1.0–§1.7 only; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1517_nonprofit_board_governance_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1517_nonprofit_board_governance_compliance/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

## Key counts
- Entities: **16** (Nonprofit, Bylaws, BylawsAmendment, BoardMember, BoardTerm, Committee, CommitteeAppointment, Meeting, Motion, Vote (immutable, `common_fields: false`), COIDisclosure, ExecutiveEvaluation, SuccessionPlan, Form990Filing, StateRegistration, InsurancePolicy)
- State machines: **14** — cyclic shapes on BoardMember (re-election after cool-off), Motion (table/resume), StateRegistration (renewal loop), BylawsAmendment (defeat→revise), Meeting (minutes reject/redraft), ExecutiveEvaluation (return), SuccessionPlan (stand-down), Committee (dormant↔active)
- Concurrency rules: **3** OCC rules (meeting minutes, evaluation scores, nonprofit profile — all 412 `ERR_STALE_VERSION`, all exercised with `${var}`-captured versions)
- Calculations: **12**, including 3 dual-variant (quorum SEATED-vs-AUTHORIZED on Meeting; registration fee ACTUAL-vs-ESTIMATED on StateRegistration; evaluation composite UNWEIGHTED-vs-WEIGHTED on ExecutiveEvaluation) and combinatorial formulas in modes (a) amendment threshold with depleted-board branch + nested max/ceil and (b) renewal fee with pinned nested rounding order
- Validations: **22** ordered priorities; **56** error codes (every one triggered by at least one design instance)
- Endpoints: **99** (flat topology under `/boardgov`, filtered-list FK reverse-reachability everywhere, plus `/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default)
- Roles: **6** — segregation-of-duties model (COI filer≠reviewer, 990 preparer≠approver, eval scorer≠ratifier, minutes recorder≠approver, self-service voting/disclosure); BoardChair/BoardDirector/Treasurer are `entity_backed:BoardMember` with officer-role qualification
- §1.8 instances: **24** (all 9 rules; 2–3 per rule; every formula-derived assert pre-computed, e.g. fee 2,550,000 vs 30,000; eval 3.40 vs 3.80; amendment required votes 5 via the vacancy branch)
- §1.9 instances: **78** (73 active + 5 `excluded_because` stubs), 1,171 total calls scanned

## Lint verdict (verbatim)
`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Design decisions worth recording
- **Posture-driven gating**: `Nonprofit.compliance_posture` (NON_COMPLIANT/AT_RISK/COMPLIANT) aggregates registrations, 990, D&O coverage, and COI delinquency; NON_COMPLIANT blocks new FUNDRAISING motions and a registration lapse cascade auto-withdraws open ones. The §1.9 "posture ladder" instance walks all four posture states via remediation.
- **Founding-adoption deadlock avoided**: founding bylaws are adopted by GovernanceAdmin (incorporator), since BoardChair identity requires an ACTIVE member and elections require adopted bylaws; GovernanceAdmin can also draft amendments for the same reachability reason.
- **COI reviewer bootstrap**: reviewer needs their own same-FY disclosure in any non-terminal state (FILED suffices), otherwise the first review of a fiscal year would be impossible.
- **Three distinct interval semantics** for Rule 8: BoardTerm half-open adjacency-allowed, Meeting 30-minute buffered exclusion, InsurancePolicy adjacency-required renewal chains.
- **Bylaws version-pinning**: BoardTerm stores `bylaws_id` at election, so amendment adoption (Rule 4 cascade) changes future term lengths without mutating in-flight terms — asserted via a 2y→3y amendment changing a new term's end date to 2029-08-01.
- Hard-constraint compliance: no sibling `task_*` directory was listed, read, or searched at any point; the design is derived solely from the scenario text plus the skill spec.

</details>

## Step 3: Copy Shared Files — 2026-08-13T19:48:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1517_nonprofit_board_governance_compliance/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T19:55:00.000Z

The PRD is complete and all audits pass. The Contract 2 rule-coverage walkthrough (done against the scaffold while drafting) confirms every category is expressed.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1517_nonprofit_board_governance_compliance/workspace/PRD.md`

**Section structure (418 lines, 19 subsections):**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role identity semantics (entity-backed `BoardChair`/`BoardDirector`/`Treasurer` vs opaque `GovernanceAdmin`/`ComplianceOfficer`/`ExecutiveDirector`), 2.2 API Response Structure (byte-verbatim block), 2.3 Pagination + list filtering, 2.4 Logical Clock and Compliance Sweep, 2.5 Common Resource Properties (incl. `Vote`'s reduced shape), 2.6 OCC (all 3 rules), 2.7 Validation Order of Precedence (all 22 priorities + `ERR_INVALID_REQUEST` short-circuit position), 2.8 three coexisting interval semantics, 2.9 monetary precision, 2.10 cascade-chain map
- §3 Business Logic (9 subsections): incorporation/bylaws/amendments, directors/terms/recruitment matrix, committees/appointments, meetings/quorum/minutes, motions/voting/outcomes, COI disclosure/restrictions, executive evaluation/succession, Form 990 lifecycle, registrations/insurance/compliance posture
- §4 Endpoint table (99 rows, 4 columns, exact scaffold roles) — verified 99/99 method+path matches
- §5 Error catalogue (56 rows, 2 columns) — verified 56/56 ids and statuses

**Zero-Silence self-audit (§1.1–§1.7 verbatim-derivability):** PASS on all seven scaffold rule tables — all 112 entity fields with types/defaults/constraints in prose; all 75 state-transition from/to pairs named with preconditions paired to error ids and side effects stated; all 12 calculations fully expressed (quorum bases incl. equality-passes, motion thresholds incl. TWO_THIRDS-of-5=4, amendment threshold with 0.75 depletion branch and max-2 floor, 4-tier fee ladder with boundary-to-lower-tier rule and pinned ceil→round-half-up→sum order, weighted/unweighted composites with the 3.40/3.80 worked example, term-chain adjacency with cool-off equality, filing deadline arithmetic, SEATED-always review coverage, open-seat invariant, full posture rule set, gap/overlap/buffer interval rules); all 22 validation priorities stated in order with scopes; all 99 endpoints and 56 errors tabulated; all 6 roles with identity translation.

**Hard Contracts:**
- Contract 1 (Field-Name Coverage): **PASS** — 128 required, 128 present, 0 missing (includes endpoint-only inputs `to_iso8601`, `expected_*_version`, `paid_fee_cents`, `reason`, `approving_meeting_id`, `rejecting_meeting_id`, `skill`, `limit`, `offset`, and computed-read outputs `current_utc`, `by_skill`, `uncovered_skills`, `active_members`, `open_seats`)
- Contract 2 (Rule Coverage): **PASS** — 22/22 validation priorities; 3/3 OCC rules (endpoint + expected-version field + `ERR_STALE_VERSION`/412 each); 75/75 transitions; 12/12 calculations; all 56 error conditions matchable in prose; all cascade chains (departure, COI restriction with the FINANCE/PERSONNEL/GOVERNANCE→committee-type mapping, bylaws adoption, lapse-withdrawal, supersede pairs) stated; sibling branches (SEATED/AUTHORIZED, ACTUAL/ESTIMATED, UNWEIGHTED/WEIGHTED, resign/remove, dissolve from three states, cancel from three states, withdraw from two states) at equal density
- Contract 3 (§3 Path Purity): **PASS** — 757 backtick tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos
- Bonus checks: 56/56 error ids in §2/§3 prose; 99/99 enum/state values present (`ENDED` gap found and fixed)

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T21:05:00.000Z

All audits pass. The suite is complete and verified. Final summary:

## Summary

**Task 1517 (nonprofit_board_governance_compliance)** — test infrastructure and claim-driven suite generated from the two design indices against `workspace/PRD.md`.

### Test counts
- **Queue A (Difficulty): 24/24 instances covered, 48 tests** — exactly 2 tests per instance (success/failure or link-1/link-2 splits), each tagged `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner): 69/73 non-stub instances covered, 69 tests** — 1 test each, tagged `Design: Corner/<section>/<instance.name>`. The 5 `excluded_because:` stubs were not translated (cross-references all resolve to real queue-A instances).
- **Total: 117 tests**, all collected cleanly by pytest.

### Instances skipped (PRD-first filter; gaps left as gaps)
- `Corner/entities/meeting_quorum_fields_null_until_call_to_order` — PRD §3.4 says a successful call *persists* the quorum fields but never pins the pre-call representation (null vs absent vs false); not uniquely derivable.
- `Corner/entities/form990_amendment_of_unfiled_target_rejected` — PRD §3.8 requires the supersede target be FILED/PUBLIC_DISCLOSED but never names the error_id surfaced on violation (ERR_INVALID_STATE vs ERR_REFERENCED_NOT_FOUND vs ERR_INVALID_REQUEST all defensible).
- `Corner/validations/unknown_role_header_returns_400` — an unrecognized role is plausibly either a 400 invalid-context-header or a 403 role-not-on-list; §2.7 rules 1–2 leave it ambiguous.
- `Corner/validations/body_fk_not_found_returns_422` — PRD §2.7 rule 6 enumerates body-FK fields for ERR_REFERENCED_NOT_FOUND and `nonprofit_id` (the field this instance probes) is not in the list.

### Recipe corrections applied (PRD-contradicting setups fixed, asserted claims preserved)
- `coverage_floor_exact_boundary` and `insurance_renewal_gap_and_overlap_detection`: the recipes bind a second policy while a rejected first quote is still QUOTED — per PRD §2.8, QUOTED is non-terminal and would force ERR_POLICY_OVERLAP on the success path. The translations cancel the rejected quote (PRD: "a QUOTED policy cancels quietly") before binding the at-floor/abutting policy, keeping all asserted error ids and the BOUND outcome intact.
- `insurance_renewal_gap_and_overlap_detection`: `gap_days == 0` asserted on the post-bind payload, since PRD §3.9 pins the gap computation to bind time, not create time.

### File inventory
- `test_helpers/` (all under `/home/ubuntu/github/CodingPRD/tasks/task_1517_nonprofit_board_governance_compliance/test_helpers/`): `__init__.py` (barrel), `types.py` (enums + TypedDicts; Vote correctly omits `updated_at`/`version` per common_fields:false), `api_client.py` (one method per endpoint, all 70+), `api_errors.py` (full §5 catalog registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts incl. append-only Vote), `factories.py`, `constants.py` (fee tiers, weights, bands, buffers), `test_users.py` (opaque constants + `make_board_chair/director/treasurer_headers` + `headers_for_member`), `fixtures.py` (composite setups: org+board, COI ring-clear, active committee, meeting-in-session, open motion, amendment motion open, evaluation scored/in-review, filing in-review/approved/filed, active D&O, clock/sweep).
- `test_suite/`: `conftest.py` plus `test_01_organizations_and_bylaws.py` (9), `test_02_directors_terms_seats.py` (18), `test_03_committees_appointments.py` (8), `test_04_meetings_quorum_minutes.py` (12), `test_05_motions_and_votes.py` (14), `test_06_amendment_adoption.py` (6), `test_07_coi_and_cascades.py` (9), `test_08_evaluations_succession.py` (12), `test_09_form990_filings.py` (8), `test_10_registrations_insurance_posture.py` (18), `test_11_rbac.py` (3).

### Stage 2 tag audit result
All 117 tests carry **exactly one** Design tag; every tag resolves to an existing instance in the source YAMLs; queue A coverage 24/24 at ≥2 tests; queue B coverage 69/69 emitted at ≥1; zero untagged/dual-tagged/phantom tags. All docstring PRD citations verified verbatim against PRD.md (whitespace-normalized containment): 0 mismatches.

## Step 6: Generate Implementation — 2026-08-13T21:10:00.000Z

All verified and cleaned up. Final summary:

## Implementation complete: task_1517_nonprofit_board_governance_compliance

**File inventory** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1517_nonprofit_board_governance_compliance/workspace/implementation/`):

| File | Role |
|---|---|
| `start.sh` | Executable launcher; guarded install (`python3 -c "import flask"` check), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | `flask>=3.0` |
| `app.py` | Flask entry: blueprint registration, ApiError/404/405/500 handlers (all return the standard error envelope), per-request RLock, `app.run(host="0.0.0.0", port=$PORT)` |
| `store.py` | 16 in-memory dict tables keyed by id (all empty at boot — zero seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, monotonic insertion sequence |
| `helpers.py` | Response envelope (`meta.api_request_id`/`api_request_timestamp` + `response_type` + `data`), error envelope, auth priorities 1-3, typed field validators (400 on malformed), date math (add_years/add_months with day clamp), pagination (`limit`/`offset` clamped to 1-100/≥0, `total_count`/`has_more` in meta) |
| `domain.py` | Fiscal calendar, `filing_due_date` (+4mo+14d), tiered renewal fee (ceil surcharge → round-half-up late fee → sum), evaluation composites (Decimal, 2dp half-up; UNWEIGHTED vs WEIGHTED), quorum (SEATED/AUTHORIZED, ceil), amendment threshold (depleted-board branch, `max(2, ceil)`), compliance posture (a-g conditions), term-chain/trailing-run logic, all cascades, compliance sweep, 16 serializers |
| `routes/core.py` | clock, nonprofits (+sweep, +recruitment-matrix, OCC PATCH), bylaws, amendments, members, terms |
| `routes/committees.py` | committees (+activate/dissolve), appointments (+end) |
| `routes/meetings.py` | meetings (+call_to_order/adjourn/cancel/minutes/approve/reject), motions (full floor lifecycle + close_voting cascades), votes |
| `routes/compliance.py` | COI disclosures (+review/clear/impose/lift with restriction cascade), evaluations (+OCC scores/submit/return/ratify/deliver), succession plans (+approve supersede loop) |
| `routes/filings.py` | Form 990 filings (+review/approve/mark_filed/discard), state registrations (+submit/confirm/reinstate), insurance policies (+bind/activate/cancel) |

**Coverage**: 99/99 scaffold endpoints registered (verified via Flask url_map enumeration), 16/16 entities, all state machines, all 11 calculations, all 52 catalogued error IDs with correct HTTP statuses.

**Verified behavior**: 171 end-to-end checks passed across four harness scripts (run both against a live `bash start.sh` server and in-process), covering: auth/RBAC + entity-backed qualification, OCC 412s, quorum bases, all motion thresholds/bases, recusal enforcement, amendment defeat→revise→re-vote→adopt cascade (successor minting, base supersede, nonprofit version bump), POLICY register append, resignation/removal cascade (term VACATED → appointments ENDED → committee DORMANT → meetings CANCELLED, each version-bumped), lapse → FUNDRAISING withdrawal, fee tier boundaries ($25k/$100k/$500k + started-$1k overage), late fee, coverage floor, gap/overlap interval rules, posture transitions (COMPLIANT/AT_RISK/NON_COMPLIANT incl. DNO expiry warning and COI delinquency), sweep term activation/completion, and fresh-boot emptiness. Every discrepancy encountered during testing traced to bugs in my throwaway test scripts (wrong clock, leftover QUOTED policies, wrong arithmetic expectations), not the implementation.

**Notable design decisions**:
- All timestamps (entity `created_at`/`updated_at`, `adopted_at`, `filed_at`, meta timestamps) read the logical clock — fully deterministic under the test harness; wall clock is never consulted.
- Computed fields (`compliance_posture`, `current_fiscal_year`, `consecutive_terms_served`, `chain_index`, `has_active_restrictions`, `active_member_count`, motion tallies, `disclosure_overdue`) are derived on read so they're always "as of the logical clock"; stored `version`/`updated_at` still bump on every mutation including cascades per PRD §2.5.
- `filed_late` compares whole calendar dates (`filed_on.date() > due.date()`), honoring "filing ON the due date is timely"; renewal windows use instant comparisons.
- Validation order follows PRD §2.7 precedence strictly: headers → role list → basic entity qualification (403 before 404) → self-service → malformed 400 (short-circuits before existence) → path 404 → org-membership 403 → body FK 422 → state 409 → OCC 412 → business gates in priority order (cross-entity → SoD → recusal → posture → reviewer → uniqueness → eligibility → committees → intervals → windows → money → thresholds → domain-shape).
- Vote is append-only with only `id`/`created_at` (no `version`/`updated_at`); motion tallies recomputed from Vote rows on read (deterministic), so vote casts don't bump motion version.
- Succession approve surfaces `ERR_NOT_FOUND` (404) for a designee not resolving to an ACTIVE member, vs `ERR_DESIGNEE_REQUIRED` (409) when absent — per PRD §3.7's explicit split.
- `start.sh` guards the pip install so per-test-server reboots are no-op fast.

## Step 7: Test-Fix Iteration Loop — 2026-08-13T21:25:00.000Z

Clean 8-round parallel sweep: **117/117 passed in every round, 0 failed, 0 errors.**

## Summary

- **Iterations run:** 2 (initial sweep: 17 deterministic failures in all 8 rounds; second sweep after fixes: all 8 rounds fully green).

- **Tests deleted:** none. Every failing test traced to a verbatim PRD rule; all were fixable as test-artifact bugs.

- **Fixes applied to `test_helpers/`:**
  - `assertions.py` — added `assert_instant_eq(actual, expected, msg)` (plus a private `_parse_iso`): instant equality for domain date fields. PRD §2.2/§2.5 pin three-fractional-digit rendering only for `api_request_timestamp`/`created_at`/`updated_at`; the rendering of domain date fields (`start_date`, `end_date`, `filing_due_date`, `current_period_end`) is unspecified, so exact-string equality was not uniquely derivable (two PRD-faithful serializers diverge on `.000Z` vs `Z`). STEP 1c split: kept the covered instant/calendar-arithmetic assertion, removed the format coupling.
  - `__init__.py` — re-exported `assert_instant_eq` from `.assertions`, and added the missing `create_vote_payload` re-export from `.factories` (the factory existed but was absent from the barrel, causing `AttributeError` in 6 vote tests; a test_helpers bug, not an implementation bug).

- **Fixes applied to `test_suite/`:**
  - `test_02_directors_terms_seats.py` (5 sites), `test_06_amendment_adoption.py` (1), `test_09_form990_filings.py` (2), `test_10_registrations_insurance_posture.py` (2) — replaced exact-string datetime equality with `th.assert_instant_eq(...)`, preserving the failure messages; the PRD-covered semantics (term end = start + N years same calendar day §3.2; future elections read amended `term_length_years` §3.5; `filing_due_date` May-15 derivation §3.8; reinstate/confirm period rolls §3.9) are asserted at full strength.
  - `test_04_meetings_quorum_minutes.py` — `test_quorum_one_short_rejected` and `test_quorum_ceil_half_rounds_up`: added `fx.set_clock("2026-08-01T02:00:00Z")` before calling the 02:00-scheduled meeting to order. The fixture previously issued the call while the logical clock (default 00:00) hadn't reached `scheduled_start`, so PRD §2.7 precedence (#19 window rules before #21 aggregate thresholds) correctly produced `ERR_MEETING_TOO_EARLY` instead of the quorum error the test meant to exercise. Advancing the clock via the PRD §2.4 capability makes the setup PRD-consistent and isolates the quorum gate.

- **Fixes applied to `implementation/`:** none. The implementation was PRD-faithful in every failure (correct instants with `.000Z` rendering, correct error precedence, correct fee/term/quorum arithmetic).

No flaky tests surfaced: the 17 failures were deterministic (failed in all 8 rounds of sweep 1), and sweep 2 passed 117/117 in all 8 rounds.

## Step 8: Finalize PRD — 2026-08-13T21:35:00.000Z

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1517_nonprofit_board_governance_compliance/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 418 lines; PRD_FINALIZED.md = 419 lines; delta = +1 line (+0.24%). The diff is a single inserted bullet; all other prose is verbatim.

### Changes (one edit total)

- **§2.2 (API Response Structure)** — **insert** — added one bullet after the `api_request_timestamp` bullet pinning that every date/datetime field in any response body (not only `api_request_timestamp`/`created_at`/`updated_at`) is rendered as ISO 8601 UTC with exactly three fractional digits (e.g. `2026-08-01T00:00:00.000Z`), with a non-exhaustive example list covering term `start_date`/`end_date`, meeting `scheduled_start`/`notice_sent_at`, bylaws `adopted_at`, disclosure `filed_at`, filing `filing_due_date`/`filed_on`/`public_disclosure_posted_at`, registration `current_period_end`, policy `policy_start_date`/`policy_end_date`, `adopted_policies[].adopted_at`, and the clock endpoint's `current_utc` — impl: `implementation/helpers.py:30-33` (`iso()`, the sole rendering helper), call sites `implementation/domain.py:351,385,421,423,466,513-517,530,545-546`, `implementation/routes/core.py:79`, `implementation/routes/meetings.py:443,538`.

### Step 7 items disposition

- **`assertions.py` `assert_instant_eq` + 10 test-site relaxations** → the one real PRD silence (rendering of domain date fields); patched as above. The implementation pins `.000Z`-style rendering uniformly, so the finalized PRD now pins it too.
- **`test_helpers/__init__.py` barrel re-exports (`assert_instant_eq`, `create_vote_payload`)** → pure test-artifact bug; no PRD edit.
- **`test_04` `fx.set_clock(...)` advancement in the two quorum tests** → pure fixture bug. PRD §2.7 already ranks window rules (#19, `ERR_MEETING_TOO_EARLY`) above aggregate thresholds (#21, `ERR_QUORUM_NOT_MET`), and §3.4 already pins the clock-must-reach-`scheduled_start` gate; prose kept verbatim, no edit.

### Pre-edit search log (mandatory per edit)

**Edit 1 (§2.2 rendering bullet):**
- (a) **Subject:** serialization format of date/datetime fields in API responses.
- (b) **Impl paths enumerated:** grep for `iso(`, `strftime`, `isoformat`, `.date()` across `implementation/` (excluding `__pycache__`). Rendering paths found and read: `helpers.py:30-33` (`iso()` — `%Y-%m-%dT%H:%M:%S.` + 3-digit millis + `Z`), `helpers.py:36-37` (`now_iso`), `helpers.py:41` (envelope `api_request_timestamp`), `helpers.py:96-99` (`new_entity` `created_at`/`updated_at`), `helpers.py:102-104` (`touch` `updated_at`), `domain.py:351` (bylaws `adopted_at`), `domain.py:385` (term `start_date`/`end_date`), `domain.py:421,423` (meeting `scheduled_start`/`notice_sent_at`), `domain.py:466` (disclosure `filed_at`), `domain.py:513-517` (filing `filing_due_date`/`filed_on`/`public_disclosure_posted_at`), `domain.py:530` (registration `current_period_end`), `domain.py:545-546` (policy `policy_start_date`/`policy_end_date`), `routes/core.py:79` (clock `current_utc`), `routes/meetings.py:443` (`adopted_policies[].adopted_at` via `now_iso()`), `routes/meetings.py:538` (vote `created_at` via `now_iso()`). The only `.date()` hit (`filings.py:176`) is a comparison, not serialization. Every enumerated path renders exactly three fractional digits UTC — the universal wording is consistent with all of them.
- (c) **Wording adjustment:** chose a universal claim ("every date or datetime field appearing anywhere in a response body") with an explicitly non-exhaustive "for example" list, rather than a closed enumeration — this keeps off-Step-7 paths (register-entry `adopted_at`, `current_utc`, `notice_sent_at`, `policy_*_date`, etc., which Step 7 never exercised) covered without risking an accidental exclusion.

## Step 9: PRD Completeness Scan — 2026-08-13T21:55:00.000Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1517_nonprofit_board_governance_compliance/workspace/PRD_COMPLETED.md` was produced from `PRD_FINALIZED.md` (419 lines / 76,802 chars → 420 lines / 79,926 chars; +1 line, +3,124 chars). All edits are inline inserts/revisions within existing paragraphs; no sections added.

**Totals: 19 ambiguity-pins, 5 mismatch-revisions (24 changes across 22 paragraphs).**

Changes (section — insert|revise — ambiguity|mismatch — what changed — impl evidence):

1. §2.1 — revise — mismatch — resignation self-service: removed `BoardChair` from the self-only list (impl lets BoardChair resign anyone; only `BoardDirector`/`Treasurer` are self-only) — routes/core.py:426-432
2. §2.1 — insert — ambiguity — resignation self-check fires before target id resolution (403 even for nonexistent target) — routes/core.py:430-433
3. §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (not rejected); non-integer → `ERR_INVALID_REQUEST`; list sort ties broken by creation sequence — helpers.py:254-289
4. §2.5 — insert — ambiguity — `created_at`/all server timestamps stamped from the logical clock, never wall clock — helpers.py:36-38, 96-99
5. §2.5 — insert — ambiguity — `version` starts at 1 at creation — helpers.py:98
6. §2.7 item 3 — insert — ambiguity — unresolvable body `nonprofit_id`: 403 `ERR_IDENTITY_NOT_QUALIFIED` for entity-backed callers, 422 `ERR_REFERENCED_NOT_FOUND` for opaque callers; org-membership half of qualification fires right after path resolution — routes/core.py:17-27, helpers.py:148-155
7. §2.7 — revise — mismatch — malformed-body rejection moved ahead of self-service ownership (was: self-service in the "auth block" before malformed) — routes/compliance.py:36-45, routes/meetings.py:499-507
8. §2.7 item 9 — insert — ambiguity — added `ERR_BYLAWS_ALREADY_ADOPTED` to the cross-entity gate list — routes/core.py:214
9. §2.8 — insert — ambiguity — `gap_days` computed at quote creation (0 without prior) and recomputed at bind; prior policy need not share `policy_type` or status — routes/filings.py:358-361, 406-410
10. §2.9 — insert — ambiguity — Feb 29 + N years → Feb 28; month addition clamps day to month's last day; naive datetime inputs read as UTC — helpers.py:77-89, 58-70
11. §3.1 — insert — ambiguity — `state_of_incorporation` two-letter form is conventional, not validated (any non-empty string) — routes/core.py:90
12. §3.1 — insert — ambiguity — amendment `proposed_fields` keys must be among the seven knobs and values must satisfy founding-drafting ranges, else `ERR_INVALID_REQUEST` — routes/core.py:30-56
13. §3.2 — insert — ambiguity — term-chain tie-break is creation order (`created_at`, then creation sequence) — domain.py:106-116
14. §3.2 — revise — mismatch — `TERM_LIMITED_OUT` re-election restarts chain at `chain_index` 1 only when start falls after the prior chain's end; zero cool-off with exact adjacency continues the run — domain.py:119-131
15. §3.2 — insert — ambiguity — recruitment matrix reports `board_size`/`open_seats` as null when no bylaws is `ADOPTED` — routes/core.py:159-164
16. §2.4 — insert — ambiguity — sweep member transition reads the latest non-`VACATED` term; an `ACTIVE` member with none is left unchanged — domain.py:294-308
17. §3.3 — revise — mismatch — dissolution from `DORMANT` leaves still-active appointments in place (PRD claimed they had already ended) — routes/committees.py:114-126
18. §3.4 — insert — ambiguity — call to order requires an `ADOPTED` bylaws for quorum parameters, else `ERR_BYLAWS_NOT_ADOPTED` — routes/meetings.py:118-121
19. §3.5 — insert — ambiguity — motion introduction does not consult meeting state; in-session binds only where floor acts name it — routes/meetings.py:281 (no state check)
20. §3.5 — insert — ambiguity — a passed BYLAWS amendment retains its `motion_id` link; only defeat/withdrawal clears it — routes/meetings.py:415-417, 437-439, 485-489
21. §3.6 — insert — ambiguity — `restriction_categories` entries are motion-category strings validated only as non-empty strings; unrecognized categories end no appointments and force no recusal — routes/compliance.py:141-144, 157-159
22. §3.7 — insert — ambiguity — a dimension repeated within one scores submission keeps only its last entry — routes/compliance.py:199-211
23. §3.7 — revise — mismatch — plan approval supersedes only `APPROVED` plans; an `ACTIVATED` plan is not displaced (was: "at most one plan … approved or activated") — routes/compliance.py:462-467
24. §3.9 — insert — ambiguity — `state_code` two-letter form not validated; `renewal_cycle_months` must be a positive integer when supplied — routes/filings.py:223-224
25. §3.9 — revise — ambiguity — registration lapses when period end "has been reached or passed" (impl uses `t >= current_period_end`) — domain.py:312-314

(Items 1+2 were one edit; the rest map 1:1. Everything else walked — all 58 endpoints, state machines, fee/quorum/composite formulas, cascade chains, OCC guards, error precedence, serializers, filters — matched the PRD as written.)

## Post-Step-9: Final Evidence Sweep — 2026-08-13T22:05:00.000Z

The Step 7 subagent's final sweep result files were absent from `workspace/implementation/` (cleaned up before exit), so the loop subagent was resumed to re-run the full 8-round parallel sweep and retain the artifacts. All 8 `results.{1..8}.json` files are present in `workspace/implementation/`; per-round passed/total verified on disk: **117/117, failed: 0 in every round** (0 errors, 0 skipped). 3 sweeps total across the loop's lifetime; no additional fixes were needed on the final sweep.
