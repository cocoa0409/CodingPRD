# Worklog — task_2526_legislative_bill_drafting_fiscal_note_preparation

## Step 1: Create task directory — 2026-09-03T05:30:36.265Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2526_legislative_bill_drafting_fiscal_note_preparation` and its `workspace/` subdirectory. Index 2526 was pre-assigned by the orchestrating command (no auto-allocation scan performed, per instruction, because up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T07:16:11.247Z

All three scaffold artifacts for task 2526 are complete and lint clean.

## Output files
`/home/ubuntu/github/CodingPRD/tasks/task_2526_legislative_bill_drafting_fiscal_note_preparation/`

| file | lines |
|---|---|
| `SCAFFOLD.yaml` (§1.0–§1.7) | 2716 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8) | 2075 |
| `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9) | 7005 |

(directory also holds the pre-existing `worklog.md` and empty `workspace/`)

## SCAFFOLD.yaml counts
14 entities (24 FKs, all reverse-reachable) · 59 endpoints (24 GET / 35 POST) · 10 state machines / 53 transitions · 3 concurrency rules · 12 calculations (4 dual-variant) · 44 ordered validations · 69 error codes · 7 roles · `difficulty_level: above_expert`, `role_model: segregation_of_duties`, `entity_topology: graph`, `state_machine_shape: cyclic`, `consistency_model: immediate`.

## §1.8 — 9 rules × 2 instances = 18

## §1.9 — 102 instances (78 full recipes, 24 stubs), sections in spec order
entities 13 (13/0) · state_machines 18 (14/4) · calculations 15 (8/7) · validations 18 (13/5) · endpoints 8 (6/2) · errors 11 (11/0) · rbac 9 (8/1) · cross_cutting_complexity_layers 8 (4/4) · consistency_model 2 (1/1)

## Verification
- All 69 declared error codes are triggered somewhere in §1.8/§1.9 (audited programmatically; the last gaps — the four late-lifecycle `ERR_INVALID_*_STATE` codes, the three deadline codes, `ERR_FISCAL_COMMITTEE_REFERRAL_REQUIRED` and the three `ERR_STALE_*_VERSION` codes — are covered by the new `errors` and `cross_cutting` instances).
- Each §1.2.1 concurrency rule has its own OCC instance using that rule's declared `write_endpoint` and `occ_field`.
- Names unique across both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 name; no stub carries a `test_recipe`; no forbidden concurrency vocabulary remains.
- Hard constraint honoured: no sibling `tasks/task_*/` directory was listed, globbed, grepped or read.

## Five coherence fixes made to SCAFFOLD.yaml while writing §1.9
1. Priority 55 (`ERR_CONFIDENTIAL_ACCESS_DENIED`) rewritten — AgencyAnalyst is stopped at priority 20 instead, since §1.5/§1.7 grant it no drafting-pipeline read; catalog condition updated to match.
2. Priority 50 (`ERR_NOT_RESOURCE_OWNER`) extended to `GET /agencies/{id} when the acting role is AgencyAnalyst`, matching §1.7's "own agency" scoping.
3. Priority 30 (`ERR_SENIOR_COUNSEL_REQUIRED`) `applies_to` now includes `POST /drafting-requests/{id}/assign` (a ReviewCounsel exclusive that the list had omitted).
4. Clerk's §1.7 read surface corrected to "every GET in §1.5" — §1.5 does list Clerk on `GET /agencies/{id}`, which note routing needs.
5. AgencyAnalyst description clarified as having no drafting-request/statutory-conflict read at all.

## Final lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     78
  Calls scanned (§1.8+§1.9):  1710

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Orchestrator verification: all three files present, `wc -l` matches the reported counts, and each parses as YAML with the expected top-level keys (`SCAFFOLD.yaml` has neither design key; the two design files each have exactly their single top-level key).

## Step 3: Copy shared files — 2026-09-03T07:16:29.641Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T07:31:51.998Z

PRD generation complete and verified.

**Output:** `workspace/PRD.md` — **488 lines**, ends at the last row of the §5 error table (real section boundary, no audit footer, no mid-sentence truncation).

Built with 11 verified chunked heredoc appends plus one targeted repair edit. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read. All worked-example numbers come from SCAFFOLD.yaml's own comment blocks.

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 The Logical Session Clock · 2.5 Common Resource Properties · 2.6 Optimistic Concurrency on Parent Records · 2.7 Reference Resolution: Paths First, Then Bodies · 2.8 Confidentiality of Drafting Files · 2.9 Cents, Rounding and Ledger Discipline · 2.10 Cascades, Counters and Compensating Actions · 2.11 The Order of Refusal (23-rung ladder)
- §3 Business Logic & Workflows: 3.1 Session standup · 3.2 Drafting intake & member priority · 3.3 Assignment, research & drafter occupancy · 3.4 Statutory conflicts, clarification loops & style certification · 3.5 Introduction, numbering, companions & referral · 3.6 Committee action, reporting & passage · 3.7 Fiscal note routing, cost methodology & projections · 3.8 Amendments, turnaround & the fiscal re-opening cascade · 3.9 Enrollment, corrections, signatures & adjournment
- §4 Endpoint Definitions (intro + 59-row, 4-column table)
- §5 Error Code Catalogue (69-row, 2-column table)

**Coverage (documented vs declared)**
| Item | Declared | Documented |
|---|---|---|
| Endpoints | 59 (24 GET / 35 POST) | 59/59 paths in §4 table |
| Entities | 14 | 14/14; all 154 required field names present in backticks |
| State machines | 10 (53 transitions) | 10/10; every declared state name present |
| Calculations | 12 (4 with variants) | 12/12; all named constants present numerically; both branches of each variant pair documented |
| Validations | 44 | 44/44 as the priority-ordered §2.11 ladder + in-context restatement |
| Error codes | 69 | 69/69 in §5 table and 69/69 also named in §2/§3 prose |

**Hard Contract 1 — Field-Name Coverage: PASS.** 154 required names (entity fields + endpoint inputs + path params) extracted from SCAFFOLD.yaml; diffed against 432 backticked tokens in PRD.md (fenced code blocks excluded from pairing). `required − actual` = ∅. All enum/allowed values also present.

**Hard Contract 2 — Rule Coverage: PASS.** All six high-risk categories walked: (a) `validations[].priority` rendered as an explicit 23-rung ladder with stop-at-first semantics; (b) all three `concurrency_rules` in §2.6 with endpoint + OCC field + error + 412; (c) cross-entity side effects written out including the 8-bullet adjourn fan-out, the L1–L3 drafting cascade and the L1–L4 fiscal decertification cascade with its reverse-order compensating restoration; (d) `applies_to` scopes respected (e.g. `ERR_UNAPPLIED_CORRECTIONS` scoped to the `GOVERNOR_TRANSMITTAL` step only, `ERR_CONFIDENTIAL_ACCESS_DENIED` to the three read shapes, `ERR_SENIOR_COUNSEL_REQUIRED` to the four ReviewCounsel ops); (e) field-level structured content (`assumption_note`, `required_fiscal_years`, `included_in_certification` invariant, `expected_next_signature` chain); (f) sibling-branch symmetry — both complexity variants (including the deliberate absence of the appropriation tier bonus in the actual variant), both cost methodologies, and supplied-vs-derived scenario seeding (multiplier not applied to a supplied row). One repair was applied during verification: `ERR_INVALID_AMENDMENT_STATE` existed only in the §5 table, so §3.8 now names it on the draft/adopt/reject/rescind status gates.

**Hard Contract 3 — §3 Path Purity: PASS.** 960 backticked tokens in the §3 span: 0 `/`-leading tokens, 0 tokens containing `/` at all, 0 bare HTTP methods, 0 method+path combos.

Orchestrator anti-truncation check (per the known doc-generator failure mode): `tail -12` shows PRD.md ending on the final `ERR_FISCAL_COMMITTEE_REFERRAL_REQUIRED | 409` table row — a clean section boundary, not mid-sentence. Independently counted 69 error rows (69 unique codes) in §5 and 59 GET/POST rows in §4, matching the scaffold's declared counts. 101,137 bytes across 488 lines (dense long-line prose). No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T08:11:24.000Z

Implementation complete and verified.

## Files written
`workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` | (399 B, +x) | guarded `pip install` then `exec python3 app.py`, `PORT` default 10000, binds 0.0.0.0 |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `app.py` | 96 | app factory, 7 blueprints, error handlers, request lock + commit/rollback |
| `store.py` | 200 | in-memory dicts, logical clock, per-request version/updated_at tracker |
| `errors.py` | 97 | 69 error IDs + HTTP statuses |
| `envelope.py` | 56 | `meta`/`response_type`/`data`, `req_`+20 alnum, 3-digit ISO |
| `validation.py` | 235 | payload shape, pagination, enum/int/cents guards |
| `auth.py` | 55 | `X-User-ID`/`X-User-Role`, 7 roles, seniority |
| `lookups.py` | 101 | path-existence resolvers (rung 4) |
| `calc.py` | 413 | all 12 calculations, `round_half_up` via `Fraction` |
| `counters.py` | 197 | derived counters/aggregates, ledger + posture recompute |
| `serializers.py` | 293 | 14 entity serializers |
| `routes_reference.py` | 324 | clock, sessions, convene/adjourn, committees, members, drafters, agencies |
| `routes_reads.py` | 404 | all 24 GETs |
| `routes_drafting.py` | 342 | drafting requests, assignment, research, review, conflicts, clarify, withdraw |
| `routes_bills.py` | 323 | introduce, companion link, referrals, report, pass, enroll |
| `routes_fiscal.py` | 265 | route note, cost estimates, submit, return, certify |
| `routes_amendments.py` | 289 | create/draft/adopt/reject/rescind + fiscal decertification cascade & reverse |
| `routes_enrollment.py` | 135 | technical corrections, apply, signatures, transmittal |

Total 3,825 lines of Python across 18 modules. No `__pycache__`, no data files on disk.

## Endpoint parity
Flask registers exactly **59 routes — 24 GET + 35 POST**, matching the 59 declared in `SCAFFOLD.yaml`; a set-diff of method+path against the scaffold is empty in both directions. Error catalog also matches exactly: 69 IDs with identical HTTP statuses across `SCAFFOLD.yaml`, PRD §5 and `errors.py`.

## Verification results
1. **Compile**: `python3 -m py_compile *.py` — all 18 files pass, no failures.
2. **Boot test**: fresh `PORT=18777 bash start.sh` answered within 1 s. `GET /sessions` → `{"data":[], "meta":{limit:10, offset:0, total_count:0, has_more:false, api_request_id:"req_6YCPN8Q5YCNB25IQ4NMO", api_request_timestamp:"2026-08-01T00:00:00.000Z"}, "response_type":"array"}` — confirming the store boots **empty** (nothing seeded) and the clock starts at the PRD default. `POST /sessions` returned a well-formed 201 object with all derived fields at their zero values (`version:1`, `status:"PENDING"`, `next_house_bill_number:1`, `fiscal_posture:"NORMAL"`). Unauthenticated request → 401 `ERR_UNAUTHENTICATED` with error `meta` containing exactly the two required keys. Server stopped cleanly afterwards; port 18777 now closed.
3. **`ls -la`**: 20 files as tabulated above.

## Behavioral smoke coverage (3 scripts, ~197 assertions, 0 failures)
Full pipeline session→drafting→bill→referral→fiscal note→amendment cascade→enrollment→signature; plus pagination/envelope/clock monotonicity; plus edge cases. Notable confirmations: certify posts 42,675,120 to the ledger and flips posture to CONSTRAINED, amendment adopt decertifies to `NOTE_STALE` with ledger back to 0, and rescind restores the ledger **bit-identically**; drafter capacity uses closed intervals (touching endpoints refused, +1 s admitted) while hearing windows are half-open with the 30-minute changeover buffer (10:20 refused, 10:30 admitted); confidential requests 403 on single read and are silently omitted from collections *including* `total_count`; intake hold trips at 2 pending clarifications; `clarify` is Member-only with required `clarification_note` and recomputes the SLA from the current clock (score 12→21).

One real bug was found and fixed during verification: version bumps were being applied in `after_request`, i.e. after `jsonify` had already serialized the body, so mutation responses returned the pre-bump `version`. The bump now happens inside `_Tracker.mark()` (immediately, once per row per request), with `_new` flags cleared at `begin_request`/`commit`/`rollback` so newly created rows still report `version: 1`.

Orchestrator note: Step 5 (unit tests) was launched in the SAME assistant message as Step 6, so the impl generator was physically isolated from `test_suite/` (the directory did not yet exist at its spawn). Step 5 was still running when this entry was written.

## Step 5: Generate unit tests — 2026-09-03T09:26:00.000Z

Generation is complete. Both queues are fully translated, and no instance was skipped.

## Files written

**`test_helpers/` (Stage 1, 9 modules, 2,617 lines)** — `__init__.py` 39, `api_client.py` 396, `api_errors.py` 176, `assertions.py` 359, `constants.py` 95, `factories.py` 256, `fixtures.py` 791, `test_users.py` 75, `types.py` 430.

**`test_suite/` (Stage 2, conftest + 21 test modules, 8,806 lines)**

Queue A (depth index, 12 files / **36 tests** over 18 difficulty instances): test_01 268, test_02 116, test_03 105, test_04 149, test_05 165, test_06 139, test_07 128, test_08 222, test_09 246, test_10 233, test_11 252, test_12 274.

Queue B (breadth index, 9 files / **78 tests** over 78 corner instances): test_13_corner_entities 618, test_14_corner_state_machines 862, test_15_corner_calculations 632, test_16_corner_validations 955, test_17_corner_endpoints 629, test_18_corner_errors 1026, test_19_corner_rbac 1041, test_20_corner_cross_cutting 532, test_21_corner_consistency 169. (test_20 and test_21 were written this session: the three optimistic-concurrency token instances plus the derived-counter reconciliation, and the immediate-consistency instance.)

## Verification sweeps (all clean)

- **Tag sweep (AST-based):** 114 test functions, each with exactly one `Design:` line as the last docstring line. 36 resolve to `Difficulty/...`, 78 to `Corner/...`; zero bogus tags. Coverage: 18/18 difficulty instances (every one with >=2 tests) and 78/78 non-stub corner instances (>=1 test each).
- **Stub discipline:** 24 `excluded_because:` corner stubs left untranslated; every one of their `difficulty_instance` cross-references resolves against `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.
- **Citation sweep:** 336 quoted PRD fragments, all verbatim against whitespace-normalized `workspace/PRD.md`. Three defects found and repaired this session — a paraphrased referral-success sentence in test_16 and two silently de-sectioned sentences in test_19 (the endpoint-role refusal and the certification effects) were replaced with genuinely section-mark-free verbatim sentences (PRD lines 248, 151, 134).
- **Forbidden-reference sweep:** `grep -rniE "scaffold|<section-mark>"` over both directories returns nothing.
- **Compile:** `pyflakes` clean on all `test_suite/*.py` (only the expected `# noqa: F401` barrel re-export notices in `test_helpers/__init__.py`); `python3 -m py_compile` over all 31 generated files -> OK; `pytest --collect-only` collects 114 tests with no import errors.

## Instances SKIPPED: none

No instance failed the PRD-first filter outright. Four faithful substitutions were needed where a design recipe named something the PRD does not declare — each preserves the instance's claim rather than weakening it: invented enum values replaced with real ones (`CITATION_FIX`/`TYPOGRAPHICAL`/`SUBSTANTIVE_ERROR` -> `CITATION`/`TYPO`/`CROSS_REFERENCE`); `revision_round` recipes that are consistently off by one corrected to the PRD's numbering (a fresh note is round 0, the first return round 1); the corner design's inverted `clarify` direction corrected to the PRD's `RETURNED_FOR_CLARIFICATION` -> `DRAFTING`; and one `ERR_INVALID_ENROLLMENT_STATE` probe re-pointed from a fourth signature (which the PRD uniquely derives to `ERR_SIGNATURE_OUT_OF_ORDER`) to a late correction proposal. One unverifiable sub-assertion was dropped: the rbac instance asks that "no Member row is created" after a 403 on `POST /members`, but the PRD declares no `GET /members` collection.

Orchestrator verification: 114 `def test_` functions across 21 files, 114 `Design:` tag lines (1:1).

## Step 7: Run tests and iterate — 2026-09-03T09:42:00.000Z

Clean 8-round sweep achieved. Note: no implementation changes were needed at all — every one of the 34 failures was a test-artifact defect.

## Summary

**Iterations run:** 2 (sweep 1 -> diagnose + fix -> sweep 2 clean).

**Sweep 1:** 80/114 in all 8 rounds, with the *identical* 34 failures every round — zero flakiness, so every failure was a real deterministic defect. Five root causes.

**Tests deleted:** none. No test asserted a scaffold-only rule; every failing test's rule traced to PRD prose. Three individual *assertions* were removed for PRD silence (see below), under STEP 1c partial-coverage handling.

**Fixes applied to `test_helpers/`**
- `test_helpers/assertions.py` — added `parse_instant()` + `assert_instant()`. PRD §2.5 pins the three-fractional-digit rendering for `created_at`/`updated_at` **only**; every domain timestamp (`convened_utc`, `research_completed_utc`, `sla_due_utc`, `due_utc`, `report_deadline_utc`, `turnaround_deadline_utc`, `reported_utc`, `routed_utc`, `requested_utc`, echoed client instants ...) is specified purely as an *instant* ("stamped with the logical clock", "added to `routed_utc`"). Sub-second rendering is under-determined, so these are now compared as instants.

**Fixes applied to `test_suite/`** (26 of the 34 failures were the one timestamp-rendering issue)
- 13 files, 51 assertion sites: `assert x["..._utc"] == "2026-...Z"` -> `assert_instant(x["..._utc"], "2026-...Z")`. The instant assertion (the PRD-covered part) is preserved byte-for-byte in intent; only the un-derivable serialization claim is dropped.
- `test_16_corner_validations.py` — `conflict_type="REPEALS_ACTIVE_SECTION"` -> `"REPEALS_ACTIVE"` (2 sites). PRD declares exactly `AMENDS_SAME_SECTION`, `REPEALS_ACTIVE`, `DUPLICATE_ENACTMENT`, `STYLE_VIOLATION`; the fixture's value was undeclared, so the PRD-faithful implementation correctly 400'd the setup.
- `test_16_corner_validations.py` — fiscal-cap test's `session_overrides` had `fiscal_cap_cents: 20_000_000` with `constrained_threshold_cents: 50_000_000`, violating PRD "`fiscal_cap_cents`, which must be at least as large as `constrained_threshold_cents`". Both now 20,000,000, which preserves the test's intent exactly (10.5M and 19.95M stay `NORMAL`; the 21M posting still crosses the cap).
- `test_16_corner_validations.py` — supersede-target test rejected an amendment still in `REQUESTED`. PRD: "A `DRAFTED` amendment moves to `REJECTED`" and "the same error answers an adopt, reject or rescind call whose amendment is not in the status that operation requires". Added the missing `draft_amendment` step before the reject.
- `test_19_corner_rbac.py` — 3 assertions on `certified_by_drafter_id` removed (**PRD-SILENCE / undeclared field**). PRD's certify-draft effects sentence enumerates exactly four effects and never mentions stamping the reviewing counsel's identity; the field appears nowhere in PRD. Replaced with the PRD-covered effects from the same sentence (`style_findings_count` stored / `sla_due_utc` cleared, and `style_findings_count is None` on the segregation refusal since only `ERR_STYLE_NONCOMPLIANT` records the count).
  - Scaffold rule that drove it: `Corner/rbac/seniority_is_a_separate_rung...` and `...segregation_of_duties_keys_on_the_identity...`, which assumed an audit field the PRD never declares.

**Fixes applied to `implementation/`:** none. No PRD-required check was removed or weakened; `workspace/implementation/` is byte-identical to what it was at the start.

**Final per-round figures (from the clean sweep's `results.{1..8}.json`, on disk at `workspace/implementation/`, written 09:34):**

| round | passed/total |
|---|---|
| 1 | 114 / 114 |
| 2 | 114 / 114 |
| 3 | 114 / 114 |
| 4 | 114 / 114 |
| 5 | 114 / 114 |
| 6 | 114 / 114 |
| 7 | 114 / 114 |
| 8 | 114 / 114 |

`pytest --collect-only` still collects 114 tests — no test was dropped or skipped, and no `skip`/`xfail` marker was added anywhere.

### Orchestrator independent verification of the Step 7 artifacts
Per the known failure mode (a Step 7 agent claiming a clean sweep with no results files behind it), the orchestrator re-checked on disk rather than trusting the report:
- `ls -la` shows all 8 `results.{1..8}.json` present in `workspace/implementation/`, each ~36 KB, all written at the same second (`09:34:21`) — consistent with 8 genuinely parallel rounds joined by `wait`, and with a setsid-wrapped sweep (no `Terminated`/same-instant-death pattern).
- Parsed each file with `json.load`: every one reports `passed=114, total=114, failed=0`.
- `pytest --collect-only -q` collects **114** tests; `grep` for `pytest.mark.skip`/`pytest.mark.xfail` across `test_suite/` and `test_helpers/` returns **0** hits.
Verdict: the clean sweep is real. Step 8 will NOT be skipped — Step 7 ran 2 iterations with `test_suite/`/`test_helpers/` fixes and three PRD-silence assertion removals, so the skip condition (zero iterations beyond baseline) does not hold, even though `implementation/` fix count is 0.

## Step 8: Finalize PRD — 2026-09-03T09:52:06.945Z

Done.

## Result

`PRD.md` 488 lines -> `PRD_FINALIZED.md` 490 lines (**+2 lines, +0.41%**). Exactly one edit.

### Changes
- **§2.5 Common Resource Properties** — *insert* — new paragraph pinning that the three-fractional-digit `Z`-suffixed UTC rendering is the API's **only** timestamp format, covering `created_at`, `updated_at`, `api_request_timestamp` and **every domain `*_utc` field**, whether stamped from the logical clock, derived by arithmetic, or supplied by the client and echoed back; client instants are normalised to UTC and re-rendered canonically (spelling not retained); unset instant fields are `null`. — `implementation/store.py:44` (`fmt_iso`), `implementation/store.py:96` (`now_iso`), `implementation/envelope.py:23`.

### Pre-edit search log
**Edit 1 — subject: rendering of every instant-valued field.**

(b) Paths enumerated / read:
- `implementation/store.py` — `fmt_iso()` (the single renderer: `"%04d-...%.03dZ"`, always 3 digits), `parse_iso()` (accepts `Z`/`z`/offset/naive, `astimezone(utc)`), `Store.now_iso()`, `create_row()` (`created_at`/`updated_at`), `_Tracker.mark()` (`updated_at` on mutation).
- `implementation/envelope.py:23` — `api_request_timestamp` on success, list **and** error envelopes.
- `implementation/serializers.py` — all 14 `*_FIELDS` tuples; `_project()` is a pass-through, so rendering is decided entirely at write time.
- `implementation/validation.py` — `req_dt()`, the only client-instant intake path.
- Exhaustive grep of every `*_utc` assignment across `routes_reference.py` (83-85, 91-92, 111, 127, 150), `routes_drafting.py` (55, 110-116, 154-155, 176, 238, 259, 298, 305, 338), `routes_bills.py` (80, 164-166, 168, 215, 315-317), `routes_fiscal.py` (89-92, 187, 256), `routes_amendments.py` (87-95, 130, 154-156, 186, 279), `routes_enrollment.py` (64, 90, 116, 122, 128). **Every** non-null value routes through `fmt_iso` or `db.now_iso()`; nulls are literal `None`.

(c) Wording adjustments made: split the claim into three clauses so it stays true off the Step 7 site — (i) explicitly listed the three provenance classes (clock-stamped, arithmetic-derived, client-echoed) since `session.introduction_deadline_utc`, `referral.hearing_window_*_utc` and `amendment.drafting_start_utc` are echoed client values that Step 7's tests never all exercised; (ii) left the accepted *input* grammar deliberately loose ("any ISO 8601 form the field's shape rule allows") rather than enumerating it, because `parse_iso` also accepts naive and date-only strings; (iii) added the explicit `null` clause so the universal "is serialized as..." sentence cannot be read as forbidding the many `*_utc` fields that start unset.

### Items deliberately **not** patched (verified PRD already determines them; pure fixture bugs)
- `REPEALS_ACTIVE` — PRD §3.4 declares exactly the four values `routes_drafting.py:32-36` accepts.
- `fiscal_cap_cents >= constrained_threshold_cents` — PRD §2.9 and §3.1 both state it; `routes_reference.py:74-78` enforces it.
- Supersede target / reject-from-`DRAFTED` — PRD §3.8 pins both (`routes_amendments.py:69-73`).
- `certified_by_drafter_id` — the field exists **nowhere** in `implementation/` (grep of all sources and serializer field lists returns zero hits). PRD is correctly silent; adding it would have created a divergence. The replacement assertions (`style_findings_count` stored, `sla_due_utc` cleared, count recorded *only* on `ERR_STYLE_NONCOMPLIANT`) are all already pinned verbatim by PRD §3.4, matching `routes_drafting.py:230-242`.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` is exactly one hunk (`99a100,101`) — the inserted §2.5 paragraph plus its blank line. No other lines differ, so the minimal-diff requirement holds.

## Step 9: Complete PRD — 2026-09-03T10:32:34.836Z

**Orchestrator decision (recorded per the AUTONOMY instruction).** The skill defines Step 9 as one subagent doing a full PRD-vs-`implementation/` scan. Against an 18-module / 3,825-line implementation, a single agent reliably shortcuts that scan and returns a PRD_COMPLETED.md byte-identical (or near-identical) to its input — the scan never actually runs. I therefore executed Step 9 as **three sequential file-partitioned passes over the same output file**, which preserves the skill's requirement (an exhaustive walk of every endpoint, transition, formula, validation, error, default, side effect, field shape and ordering rule) while making the shortcut impossible: each pass owns a named, balanced slice of the implementation and must report per-behavior verdicts for it. Passes were run strictly sequentially because they edit one file. Partition: A = cross-cutting core (app/store/errors/envelope/validation/auth/lookups/serializers, 1,133 lines); B = calc/counters/routes_reference/routes_reads (1,338 lines); C = the five workflow write-path route modules (1,354 lines). Pass A performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; B and C were explicitly forbidden from re-copying or reverting earlier passes.

### Aggregate result

`PRD_FINALIZED.md` 490 lines / 102,070 chars -> `PRD_COMPLETED.md` **492 lines / 118,172 chars** (+2 lines, **+16,102 chars**, 40 diff hunks). **42 changes: 33 ambiguity-pins, 9 mismatch-revisions.** No new sections; every edit is an in-paragraph insert or in-place revision. §4 (59 endpoint rows) and §5 (69 error rows) untouched — no hunk past line 337.

---

### PASS A — cross-cutting core (10 ambiguity-pins, 0 mismatches)

- §2.1 (RBAC headers) — insert — ambiguity — an empty header value counts as absent, and the role name is matched exactly/case-sensitively — `auth.py:27-30`
- §2.2 (success bullets) — insert — ambiguity — `api_request_id` is `req_` + twenty uppercase-alnum characters — `envelope.py:13-17`
- §2.2 (success bullets) — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not host time, so equal clock readings give equal values — `envelope.py:20-24`
- §2.2 (`data` bullet) — insert — ambiguity — a resource object carries exactly the declared fields (no internal bookkeeping), unset fields render as null, and the eight free-text `*_reason`/`*_note`/`draft_text` inputs never appear in a response payload — `serializers.py:225-232` + fixed field tuples
- §2.2 (error format, new paragraph) — insert — ambiguity — unknown path -> `ERR_INVALID_REQUEST` 404, undefined method -> `ERR_INVALID_REQUEST` 405 (the only two non-400 uses of that id), trailing slash tolerated, everything else unclassified -> 400 — `app.py:27,61-80`
- §2.3 (ordering) — insert — ambiguity — `created_at` ties (the norm under a logical clock) are broken by insertion order, and the session collection reverses both keys together — `store.py:116,124`, cross-checked `routes_reads.py:47-51`
- §2.3 (filters) — insert — ambiguity — exact/case-sensitive string matching, booleans only `true`/`false` in any case, integers only decimal, an unrepresentable filter value matches no row (empty page, `total_count` 0) rather than erroring, undeclared query params ignored — `validation.py:204-235`
- §2.5 (instant normalisation) — insert — ambiguity — an offset-less form is read as UTC; more than three fractional digits is truncated toward zero, never rounded — `store.py:24-50`
- §2.6 (concurrency intro) — insert — ambiguity — the version assertion is an integer validated at rung 7, so absent/non-integer is `ERR_INVALID_REQUEST` and only a well-shaped mismatch reaches rung 9 — `validation.py:66-78`, use sites `routes_amendments.py:39`, `routes_fiscal.py:120`, `routes_enrollment.py:40`
- §2.10 (cascade/version paragraph) — insert — ambiguity — `version` rises at most once per row per request regardless of fields/cascade levels; a row created by the request stays at `version` 1 with `updated_at == created_at`; the bump is already visible in that request's response; and where a refusal persists a value (the §3.4 style count, the only such case) the row's `version`/`updated_at` advance with it — `store.py:137-157`, `app.py:53-59,82-86`, `routes_drafting.py:232-234`
- §2.11 rung 7 — insert — ambiguity — strict typing with no coercion: explicit null == absent (required->refused, optional->default), integers reject booleans and `10.0`, strings reject numbers, booleans reject `"true"`/`"false"`, `fte_count` is the sole fractional-numeric field, required strings accept `""` while entity-naming fields must be non-empty, unknown keys ignored, absent/empty body read as `{}`, non-object body -> `ERR_INVALID_REQUEST` — `validation.py:11-129`

**Pass A verified ALREADY correctly pinned:** envelope shape (`meta`/`response_type`/`data`, error `meta` two-key limit, `"object"`/`"array"`/`"error"`, `{}` for no-data 2xx, pagination keys only on lists, `has_more = offset + len(page) < total_count`, `total_count` before the window); error catalogue (programmatic diff of `errors.ERROR_HTTP` vs §5 — 69 vs 69, no extras/omissions/status disagreements); auth/RBAC (seven roles, 401 on missing/undeclared, 403 `ERR_UNAUTHORIZED` on endpoint-role mismatch, ladder authentication -> endpoint role -> seniority -> path, seniority requires an existing `Drafter` with `is_senior` true and reports `ERR_SENIOR_COUNSEL_REQUIRED` not `ERR_DRAFTER_NOT_FOUND`); clock & timestamps (default `2026-08-01T00:00:00Z`, never host time, canonical `Z` + 3 digits, whole-day addition preserves time-of-day); identity (UUID `id` no prefix, server-minted, client `id` inert, `version` starts at 1, cost-estimate line carries only `id` + `created_at`); lookups (13 collection->not-found mappings match §2.7, left-to-right path resolution, slicing after filter+order, `ERR_SESSION_ADJOURNED` before `ERR_SESSION_NOT_CONVENED`); pagination (10/0 defaults, 1..100 and >=0, `ERR_PAGINATION_INVALID` at rung 7); shape helpers (interval strictly increasing, `required_fiscal_years` non-empty/integer/strictly ascending, enum membership, declared minima/maxima); serializers (programmatic two-way check — every serialized field named in PRD and every PRD-named resource field in its serializer, zero discrepancies; `included_in_certification` recomputed as `line.revision_round == note.revision_round`).

---

### PASS B — calc / counters / routes_reference / routes_reads (7 ambiguity-pins, 1 mismatch-revision)

- §2.10 — insert — ambiguity — a derived-counter recomputation that lands on the value the row already holds contributes no mutation, so the row's `version`/`updated_at` stay put (non-priority intake does not bump the member) — `counters.py:16-24`, observable at `routes_drafting.py:125`
- §3.1 — insert — ambiguity — convening an already-`ADJOURNED` session reports `ERR_INVALID_SESSION_STATE`, not `ERR_SESSION_ADJOURNED` — `routes_reference.py:107-109`
- §3.1 — insert — ambiguity — reference-data creation is never session-lifecycle-gated; a committee may be created beneath an `ADJOURNED` session, whose path id is resolved for existence only — `routes_reference.py:226-227`
- §3.1 — insert — ambiguity — `agency_code` uniqueness compares exactly, case-sensitively, across every agency regardless of `status` — `routes_reference.py:308-310`
- §3.2 — revise — ambiguity — `clarification_pending_count` is counted across every session, like the slot ledger — `counters.py:36-42`
- §3.5 — insert — ambiguity — `referral_count` is every referral ever created in any status, never falling back, so `referral_order` keeps climbing — `counters.py:126-128`, `routes_bills.py:163`
- §3.7 — insert — ambiguity — `included_in_certification` is the round comparison evaluated at read time, and that derived value is what the §2.3 filter compares against, not the stored flag — `routes_reads.py:316-322`, `serializers.py:275-281`
- §3.9 — revise — **mismatch** — `enrollment_sequence` broke `created_at` ties by insertion order in impl, but the PRD asserted "`created_at` ordering is the only tie-break"; revised to pin the insertion-order tie-break while keeping "identifier is never a decision input" — `calc.py:304-309`

**Pass B verified ALREADY correctly pinned:** all 12 calculations — `round_half_up` semantics incl. negative seeds; appropriation tier bonus boundaries (0 / <=5,000,000 / >); both complexity formulas incl. the dropped tier bonus and all-resolution-status conflict counting; SLA four steps (x6, clamp 24-240 *before* multipliers, x1/2 priority, x3/4 at-or-after the 14-day pressure instant, single ceiling, `min` against `introduction_deadline_utc`); `INCREMENTAL_COST` 0.5-FTE inclusive floor with no overhead; `FULL_ABSORPTION` one aggregate 0.185 rounding folded into `direct_cost_cents`; contingency tiers both-inclusive from the post-overhead subtotal; `certified_total_cents` with no further rounding; revenue projection base year, verbatim-seed-vs-1.15/0.85 fallback, per-year-then-sum rounding at 0.0325 over 4 years; responsiveness 100-12/-5 clamped 0-100 with 70/40 bands and `add_days` time-of-day preservation; turnaround 240/60 min with <=48h compression; drafter occupancy closed-interval `peak+1 <= cap`; `mint_bill_number`. Every PRD worked example re-derived (13,997,529 / 16,097,159 / 8,398,519 / 39,514,000 / 26 days / 120 h) — all match impl exactly. Also: all nine counter recompute definitions and scoping; posture's inclusive `>=`; exact integer ledger add/subtract; clock monotonicity accepting equality returning an empty data object; session-create field set/defaults (21 days, min 1)/strict deadline ordering/`cap >= threshold`/initial values; convene stamping; the full adjourn fan-out (six target sets, session scoping, post-fan-out recomputes, ledger and `fiscal_posture` untouched); committee/member/drafter/agency field sets, defaults (2/2/3, `is_fiscal_committee` false, `is_senior` false, `ACTIVE`) and 201; all 24 GET role lists match §4 exactly; ladder order rung 4->5->6->7; all 11 filter sets match §2.3 name-for-name; ascending everywhere with sessions the sole descending view (no local deviations); confidentiality omission from collections incl. `total_count`; bills/notes not confidentiality-gated; `AgencyAnalyst` reads every note, only its own `Agency`.

---

### PASS C — the five workflow write-path route modules (17 ambiguity-pins, 8 mismatch-revisions)

**Mismatch-revisions**
- §2.1 — revise — mismatch — "exactly seven" ownership operations was wrong (impl has 8 `ERR_NOT_RESOURCE_OWNER` operations); added conflict resolution, and carved out amendment drafting, whose "ownership" check is only that `X-User-ID` names a registered `Drafter` row — `routes_drafting.py:332-334`, `routes_amendments.py:112-114`
- §2.6 — revise — mismatch — removed `drafted` from the list of acts that advance a bill's `version` — `routes_amendments.py:128-133`
- §2.6 — insert — mismatch — drafting or rejecting an amendment writes only the amendment row, so neither can stale another client's `expected_bill_version` — `routes_amendments.py:128-133,220-225`
- §2.11 rung 7 — revise — mismatch — pass A's universal "a body that parses to anything other than a JSON object is `ERR_INVALID_REQUEST`" is false for the six endpoints that never call `body()` (convene, adjourn, pass, enroll, adopt amendment, apply correction); qualified to endpoints declaring at least one field — `routes_bills.py:250,279`, `routes_amendments.py:168`, `routes_enrollment.py:72`
- §3.5 — insert — mismatch — narrowed "any write against a `DEAD`/`TRANSMITTED` bill is `ERR_INVALID_BILL_STATE`" to bill-subject operations read against the *path* bill; a note opened pre-death still accepts lines/submit/return/certify and that certification still moves the dead bill's `fiscal_status` and posts to the ledger; a `DRAFTED` amendment of a dead bill may still be rejected — `routes_fiscal.py:239-265`, `routes_amendments.py:209-225`
- §3.7 — revise — mismatch — "Both the note's and the session's `version` rise by one" on certification undercounted: **four** rows rise — note, session, agency, bill — `routes_fiscal.py:255-264`, `counters.py:192-197`
- §3.8 — insert — mismatch — the rescission restoration is *not* a full inverse of level 2: the note keeps the raised `revision_round`, the re-stamped `routed_utc`/`due_utc` and its original `certified_utc`, so a restored note reads `CERTIFIED` while every line beneath it still reports `included_in_certification` false and the certified figure is no longer re-derivable; also requires the re-opened note to still be `ROUTED`, and is declared only for the `NOTE_STALE` head (a `NOT_REQUIRED`->`NOTE_PENDING` adoption is never unwound) — `routes_amendments.py:233-259`
- §3.9 — insert — mismatch — applying a technical correction requires a senior `Drafter` row (`ERR_SENIOR_COUNSEL_REQUIRED`, rung 3, above path resolution). The PRD was entirely silent on this, one of the four seniority-gated operations rung 3 counts — `routes_enrollment.py:75`

**Ambiguity-pins**
- §3.2 — insert — ambiguity — `member_id` must name a registered `Member` (`ERR_MEMBER_NOT_FOUND`), resolved *after* the body's `session_id` — `routes_drafting.py:86-89`
- §3.3 — insert — ambiguity — `affected_sections_count` may be 0 but not negative; assigned attorney only — `routes_drafting.py:168`
- §3.4 — insert — ambiguity — conflict-filing ownership is checked after payload shape and body-ref resolution, so a malformed payload from an unassigned attorney yields `ERR_INVALID_REQUEST` — `routes_drafting.py:281-283`
- §3.4 — insert — ambiguity — `RESOLVED` may be done by *any* `ReviewCounsel` (no assignment, no senior row); a non-assigned `Drafter` gets `ERR_NOT_RESOURCE_OWNER` evaluated after the conflict's state gate — `routes_drafting.py:332-334`
- §3.4 — insert — ambiguity — the `WAIVED` seniority rung is decided from a non-validating peek at the body *before* path resolution: a `Drafter` asking for `WAIVED` gets `ERR_SENIOR_COUNSEL_REQUIRED` even when the path id names nothing; an absent/unparseable/non-object body skips the rung entirely — `routes_drafting.py:316-321`
- §3.4 — insert — ambiguity — sponsor identity on clarify is a transition precondition (after shape, session, target state), so a non-sponsor on a wrong-state request gets `ERR_INVALID_DRAFTING_REQUEST_STATE` — `routes_drafting.py:186-195`
- §3.5 — insert — ambiguity — a bill number is minted only after every refusal clears; a refused introduction consumes nothing — `routes_bills.py:60-65`
- §3.5 — insert — ambiguity — the four companion refusals fire in the stated order; naming the path bill is never `ERR_BILL_NOT_FOUND`; the terminal bar applies to the path bill only so a `DEAD`/`TRANSMITTED` companion is still linkable and still version-bumped; response body is the path bill — `routes_bills.py:98-124`
- §3.6 — insert — ambiguity — the outstanding-amendment bar is a target-state-rung check evaluated ahead of the fiscal-note and sine-die refusals — `routes_bills.py:256-267`
- §3.7 — insert — ambiguity — `contingency_pct` is the one member of the computed group that is a rate, emitted as a fractional JSON number (`0.05`/`0.08`/`0.12`), never a whole-percent integer or string; the §2.9 integer-cents rule's single wire exception — `routes_fiscal.py:46`
- §3.7 — revise — ambiguity — the states admitting a cost-estimate line are exactly `ROUTED` and `RETURNED_FOR_REVISION` — `routes_fiscal.py:132`
- §3.7 — insert — ambiguity — a return rewinds nothing but status/round/counters: `submitted_utc`, `late_submission`, all cost and projection figures and `due_utc` all stand, so a resubmission is judged late against the original grant — `routes_fiscal.py:216-231`
- §3.8 — insert — ambiguity — `requested_by_member_id` is stamped, never resolved against a `Member` row (unlike a drafting request's `member_id`) — `routes_amendments.py:81`
- §3.8 — insert — ambiguity — the re-opening retains `submitted_utc`, `late_submission` and every cost/projection figure alongside `certified_total_cents`/`certified_utc` — `routes_amendments.py:141-165`
- §3.8 — insert — ambiguity — rejection does not write the bill row, so the bill's `version` stands still — `routes_amendments.py:220-225`
- §3.8 — insert — ambiguity — rescission evaluates the amendment's status before the bill's, so a `DRAFTED` amendment on an enrolled bill reports `ERR_INVALID_AMENDMENT_STATE` — `routes_amendments.py:271-274`
- §3.9 — insert — ambiguity — the substantive-correction refusal sits below the version guard and enrollment state; proposing resolves nothing about the proposer (no `Drafter` lookup, no seniority) — `routes_enrollment.py:46-52,58`
- §3.9 — insert — ambiguity — both state gates on apply precede segregation, and the correction's status precedes the enrollment's — `routes_enrollment.py:81-86`
- §3.9 — insert — ambiguity — a signature presented to a `TRANSMITTED` enrollment is `ERR_INVALID_ENROLLMENT_STATE`, not `ERR_SIGNATURE_OUT_OF_ORDER` — `routes_enrollment.py:109-112`

**Pass C verified ALREADY correctly pinned:** introduction gate order (impl session -> `DRAFT_READY` -> blocking -> deadline differs from §3.5's prose order but is exactly what §2.11 rungs 10/11/13/20 dictate); referral creation & reporting (half-open windows + 30-min buffer, `report_deadline_utc` as the earlier of window-end+7d and the session deadline, unconditional `reported_utc` in both branches, the unfavourable-branch sibling cascade, `REPORTED` advance only when no sibling remains `IN_COMMITTEE`); enrollment (all four preconditions, the frozen quartet, `origin_signature_role`/`expected_next_signature` seeding; the three internal orderings unobservable — all yield `ERR_INVALID_BILL_STATE`); signature chain (three steps, `expected_next_signature = "NONE"`, `open_corrections_count` gate after the role match — already pinned by rung 18); fiscal routing (all five refusals, opening field values, `due_utc` from the responsiveness band; terminal-check-before-`fiscal_status` unobservable, same error id); ownership at rung 5 (five handlers check ownership before `body()`, matching rung 5 < rung 7 — the only three exceptions, `create_conflict`/`clarify_request`/`resolve_conflict`, are now pinned); amendment turnaround, occupancy, stage pairing, supersession and the adjournment fan-out.

**Cross-pass hand-off points, all discharged:** the `WAIVED` body peek (pinned incl. `Drafter`+`WAIVED` and unparseable-body cases); `contingency_pct` float (pinned, reconciled with §2.9); `included_in_certification` (no contradicting "stored flag" claim added — pass C's §3.8 wording is phrased as pass B's authoritative derived comparison); referral wording (left consistent with pass B's pin); `routes_fiscal.py:190` strict-inequality lateness and direct `touch(agency)` (already pinned at §3.7); `app.py` commit-on-`ApiError` (only `certify_draft` writes before failing — covered by pass A's §3.4 text).

---

### Orchestrator final verification

- `workspace/PRD_COMPLETED.md` exists: **492 lines / 118,172 chars**, and is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 40 diff hunks) — so the scan demonstrably ran, which is the specific failure mode the three-pass split was chosen to prevent.
- Well-formed: ends on the final `| ERR_FISCAL_COMMITTEE_REFERRAL_REQUIRED | 409 |` table row (real section boundary); §4 still has **59** endpoint rows; §5 still has **69** error rows.
- `find` over `workspace/implementation/`, `test_suite/` and `test_helpers/` for `*.py` modified after the clean sweep (09:35) returns **0** files. Step 9 touched only the PRD, so the verified 8×(114/114) sweep still describes the artifacts on disk.

**PIPELINE COMPLETE.** Steps 1-9 all executed; Step 8 was not skipped (Step 7 ran 2 iterations). Final deliverables: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 modules), `test_suite/` (conftest + 21 modules, 114 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (18 modules + start.sh) with `results.{1..8}.json` all at 114/114.
