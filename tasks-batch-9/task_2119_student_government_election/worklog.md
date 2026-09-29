# Worklog — task_2119_student_government_election

## Step 1: Create task directory — 2026-08-17T12:03:20.965Z

Created `./tasks/task_2119_student_government_election/` and `./tasks/task_2119_student_government_election/workspace/`. Index 2119 chosen as max existing index (2118) + 1.

## Step 3: Copy shared files — 2026-08-17T12:03:37.917Z

Copied `./INSTRUCTION.md` -> `tasks/task_2119_student_government_election/workspace/INSTRUCTION.md` (1424 bytes). (Run out of order relative to Step 2, which is independent of it.)

## Step 2: Generate scaffold — 2026-08-17T13:23:00.000Z

All three scaffold artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_2119_student_government_election/` and pass the skill's linter.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1129

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

**Files** (absolute paths)
- `SCAFFOLD.yaml` (§1.0–§1.7, 144 KB)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

**Complexity profile** — Expert. Primary archetype `compliance_audit`, secondary `multi_party_negotiation`; layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers. Topology **flat** (every entity a top-level collection, FK-linked — `api_prefix: "/"`), state-machine shape **parallel**, role model **segregation_of_duties**, consistency **immediate**. Relationship patterns include self-referential (`Candidacy.slate_leader_candidacy_id`) and polymorphic (`BallotLine` -> Candidacy | Referendum).

**Counts**
- **12 entities**: Election, Office, Student, Candidacy, PetitionSignature, CampaignExpense, ComplianceCase, Referendum, Ballot, BallotLine, Vote, Appeal
- **12 state machines** across 10 entities, incl. two parallel-axis pairs (`Candidacy.status x transition_status`, `Referendum.drafting_status x outcome_status`), an Election fork at TALLYING (CERTIFIED vs RUNOFF_SCHEDULED with divergent side-effect sets) plus two Election cycles
- **2 concurrency rules** (OCC only): `ballot-create-stale-election` on `Election.version`, `slate-membership-stale-candidacy` on `Candidacy.version`
- **12 calculations**, incl. two dual-variant pairs on different domains (`campaign_spend_assessment` PROVISIONAL/FINAL on Candidacy money; `office_result_share` PROVISIONAL/CERTIFIED denominators on Office vote share), the pinned six-step `certification_evaluation_order` that breaks a genuine spend->penalty->disqualification->membership->spend cycle by freezing slate membership at `Ballot.locked_at`, per-line rounding in `slate_expense_allocation`, and two conservation invariants (signature row count, money in cents)
- **32 validations** (strict priority order), **64 endpoints**, **42 error codes**, **5 roles** (ElectionCommissioner, FacultyAdvisor, Registrar — opaque; Candidate, StudentVoter — `entity_backed:Student`)
- Logical clock endpoint `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default

**Design instances**
- §1.8: **19 instances** across all 9 difficulty rules (2 each, 3 for `combinatorial_formula` covering modes a/b/c). Every formula-derived assertion is a pre-computed literal (verified in Python), e.g. slate FINAL split 9168/6666/7666 vs PROVISIONAL 27500; penalty 15x1.5x1.5+20 -> 54 (total 59, no DQ) vs the exact-60 boundary that does disqualify; provisional 40.00 vs certified 66.67 flipping an office from runoff to decided.
- §1.9: **69 instances** (55 with full executable recipes, 14 `excluded_because` stubs) across all nine claim-extraction sections.

**Notable design decisions worth flagging**
- The spending cap is scoped to the *reporting* candidacy only, so joining a slate via `POST /candidacies/{id}/slate-membership` can legitimately push a member over the cap without any expense being rejected — the overrun is then caught by the compliance overspend surcharge. This makes the overspend points reachable and is the mechanism behind several instances.
- Two Rule-8 overlap geometries deliberately differ: election voting windows are **half-open with adjacency accepted**; venue bookings on `CampaignExpense` (category EVENT) are **closed intervals widened by a 30-minute teardown buffer, adjacency rejected**.
- `POST /candidacies/{id}/activate-officer` accepts `transition_status in {PENDING, TRAINING_COMPLETE}` at the priority-9 state gate so `ERR_TRAINING_INCOMPLETE` (priority 31) is reachable rather than shadowed by `ERR_INVALID_STATE`.
- No sibling task under `tasks/` was read, listed, or grepped; the scaffold derives solely from the scenario text plus the skill spec, its `references/claim-extraction-guide.md`, and `scaffold_lint.py`.

## Step 4: Generate PRD — 2026-08-17T13:36:00.000Z

The PRD is complete and all three hard contracts pass. Final verification confirms full coverage.

**Output:** `workspace/PRD.md` — **454 lines** (~98 KB).

**Document skeleton** (domain-derived, not copied from the example): §1 Introduction (3 paragraphs); §2 with 10 subsections — RBAC, the fixed Response Structure, Pagination, The Logical Election Clock, Resource Addressing and the Order of Rejection, Common Resource Properties, Counting/Money/Percentages, Version Guards on Superseding Writes, Cascade Discipline and Ledger Conservation, Two Interval Geometries; §3 with 9 subsections organised as an election-cycle timeline (opening a cycle -> filing -> petitions -> finance -> compliance -> ballot -> voting -> tally/certification -> appeals & officer transition); §4 endpoint table; §5 error table. The file ends at §5 with no audit footer.

**Coverage audit (emitted vs. scaffold):**

| Category | Scaffold | Emitted |
| --- | --- | --- |
| Entities | 12 | 12 (all 118 `fields[].name` present in backticks) |
| State machines | 12 | 12 (all 67 transitions expressed with from/to, preconditions, side effects) |
| Calculations | 12 | 12 (formulas as prose; constants embedded: 5/15/40 severity bases, 0.5 repeat step, 1.5 voting-window factor, 1000 cents/point, 25 surcharge cap, 100 point max, 60 disqualification threshold, 30-minute teardown buffer) |
| Validations | 32 | 32 (full priority-ordered ladder in §2.5 with each `error_id`, HTTP status and `applies_to` scope) |
| Endpoints | 64 | 64 rows, 4 columns |
| Error codes | 42 | 42 rows, 2 columns; all 42 also referenced in §2/§3 narrative |
| Roles | 5 | 5, each `identity:` translated (3 opaque, 2 `entity_backed:Student`) |
| Concurrency rules | 2 | 2 (`expected_election_version`/`ERR_STALE_ELECTION_VERSION` 412; `expected_candidacy_version`/`ERR_STALE_CANDIDACY_VERSION` 412) |
| State/enum values | 46 states, 76 enum values | all present verbatim |

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 118 required, 118 present, 0 missing
- endpoints[].request_body: 66 required, 66 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 32 checked, 32 expressed in prose (explicit 1..32 ladder, first-failure-wins), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 67 checked, 67 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 32 checked, 32 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 64 checked, 64 expressed, 0 missing
- entities[].fields[] structured content: 118 checked, 118 reconstructible from prose (types, defaults, initial values, enum domains), 0 missing
- sibling-branch symmetry: 7 groups checked (certify arms A/B, three ballot-create forms, three appeal remedies, three referendum outcomes, adjudicate VERIFIED/REJECTED, review APPROVE/RETURN, PROVISIONAL/FINAL spend + PROVISIONAL/CERTIFIED share), 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 752
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two notes worth flagging: §2.2 was pasted byte-identical from `section-2.2-response-structure.md` (verified programmatically). The scaffold contains two internal cross-reference slips that I resolved in favour of the actual `validations[]` table rather than the prose notes — the officer-training check is priority 30 (not 31, as two `note:` fields claim) and the signature-dedupe guarantee comes from priority 22, not 23 — so the PRD expresses these orderings relationally ("after the state gate, before the poster and spending caps") rather than by number.

**Orchestrator verification:** `wc -l` = 454; file terminates in the §5 error catalog (`ERR_SPENDING_CAP_EXCEEDED`), so no mid-document truncation.

## Step 6: Generate implementation — 2026-08-17T14:12:00.000Z

The implementation is complete and verified end-to-end.

## Files written

`workspace/implementation/` — 27 files, ~3,800 lines of Python:

- `start.sh` (guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT`, default 10000), `requirements.txt` (flask only)
- `app.py` (blueprint registration, Decimal->JSON-number provider, per-request store lock, error handlers), `db.py` (in-memory dicts + logical clock + `new_row`/`touch`/`set_fields`), `constants.py`, `errors.py` (all 42 error IDs + HTTP map), `response.py`, `auth.py`, `validation.py`, `lookup.py`, `listing.py`, `serialize.py`, `calc.py`, `cascades.py`
- `routes/` — 12 modules: elections, offices, students, candidacies, petition_signatures, campaign_expenses, compliance_cases, referenda, ballots, votes, appeals, clock

**64 endpoints** implemented (verified by enumerating the Flask URL map — exactly matches PRD §4). Storage is Python dicts only; the store is empty on every boot (verified by rebooting via `start.sh` and reading `GET /elections` -> `total_count: 0`), and the clock reads `2026-08-01T00:00:00Z` before the first `POST /_clock/set_current_utc`.

## How the three hard parts were handled

**Validation priority ladder (32 rules).** Each handler executes the ladder explicitly in ascending order rather than relying on helper side effects: auth -> role -> path params (left to right) -> body FKs *in the endpoint's input-list order* -> schema -> pagination -> ownership -> segregation of duties -> `ERR_INVALID_STATE` -> `ERR_ELECTION_PHASE_INVALID` -> OCC -> the temporal/business rules. Two PRD-only subtleties were followed literally: (a) rule 10 covers only the twelve named operations, so the phase precondition on withdrawal, signature voiding, vote voiding and ballot publish is a *state-machine* precondition and returns `ERR_INVALID_STATE`, not `ERR_ELECTION_PHASE_INVALID`; (b) expense reporting runs quiet period -> venue -> poster -> spending, and vote casting runs window -> voter eligibility -> one-vote -> selection shape. Ladder ordering is regression-tested (e.g. bad body FK + missing field -> 404; bad field type + wrong owner -> 400; wrong owner + wrong phase -> 403).

**Certification evaluation order.** `cascades.run_tally` runs STEP 1–6 once each in one request. STEP 1 reads a `_snapshot` (candidacy id + slate leader for every `ON_BALLOT` candidacy) captured on the ballot at `locked_at` — a private, non-serialized field — so membership is frozen and never re-derived. STEP 2's pro-rata allocation rounds half-up **per line** (ordered `incurred_at`, `created_at`) and assigns the possibly-negative remainder to the earliest frozen member (verified: 8000+1001 across two members -> 4500 / 4501). STEP 3 re-scores upheld cases against `spending_final_cents`, STEP 4 sweeps `ON_BALLOT` candidacies in `created_at` order without re-deriving STEP 1 or re-running STEP 2, STEP 5/6 compute the two divergent share variants and the referendum verdict order. The `certify` fork reads `runoff_required_office_count`: arm A elects/eliminates, opens transitions and stamps the certification identity; arm B qualifies (seat_count+1 plus ties) and deliberately stamps neither `certified_by_user_id` nor `certified_at`.

**OCC guards.** Exactly two, both mandatory inputs, both evaluated after the state gate: `expected_election_version` on `POST /ballots` (`ERR_STALE_ELECTION_VERSION`, 412) and `expected_candidacy_version` on slate-membership (`ERR_STALE_CANDIDACY_VERSION`, 412). A global per-request lock serializes mutations, so a concurrent race yields exactly one 201 and one 412 (verified), and the same holds for the duplicate-vote race (201/409). `version` bumps at most once per row per request while every row a cascade touches gets its own bump.

Two spec ambiguities I resolved and should be flagged: STEP 5's `invalidated_votes_count` sums raw votes over candidacies whose status *is* `DISQUALIFIED` at that point (scaffold's explicit formula; identical to the PRD's "candidacies that step four disqualified" in every normal flow), and STEP 4's disqualifications void ballot lines (declared side effect of `ON_BALLOT -> DISQUALIFIED`) but do not raise `ballot_integrity_status`, which PRD §3.5 attaches to the compliance-uphold cascade.

## Orchestrator check: unbound-constant reconciliation (per project memory `prd-bench-scaffold-unbound-constants`)

Ran the pre-Step-5 scan for ALL_CAPS constants referenced but never bound. **Result: not applicable to this task — no unbound constants.** All seven candidate constants are explicitly bound in `SCAFFOLD.yaml` (`constants:` block at lines 1841–1847, plus `TEARDOWN_BUFFER_MINUTES` at 2031):

| Constant | Scaffold | PRD.md | implementation/constants.py |
| --- | --- | --- | --- |
| `PENALTY_BASE` | MINOR 5 / MAJOR 15 / SEVERE 40 | "five points for `MINOR`, fifteen for `MAJOR`, forty for `SEVERE`" (L252) | `{"MINOR": 5, "MAJOR": 15, "SEVERE": 40}` |
| `REPEAT_STEP` | 0.5 | "one plus one half for each such prior case" (L252) | `"0.5"` |
| `VOTING_WINDOW_FACTOR` | 1.5 | `1.5` (L252) | `"1.5"` |
| `OVERSPEND_CENTS_PER_POINT` | 1000 | "divide ... by one thousand" (L252) | `1000` |
| `OVERSPEND_POINTS_CAP` | 25 | "the smaller of that number and twenty-five" (L252) | `25` |
| `PENALTY_POINTS_MAX` | 100 | "the smaller of that integer and one hundred" (L252) | `100` |
| `DISQUALIFICATION_POINT_THRESHOLD` | 60 | "sixty points — the disqualification threshold, compared as 'at least'" (L256, L304) | `60` |
| `TEARDOWN_BUFFER_MINUTES` | 30 | "thirty minutes on both sides, so adjacency is rejected" (L184) | `30` |

The PRD spells the values as English words rather than numerals, which is why a bare `grep -w 60` returns nothing — the values are nonetheless present and identical. No PRD amendment was required and no design-index literal conflicts with the PRD.

## Step 5: Generate unit tests — 2026-08-17T14:45:00.000Z

Test infrastructure and suite are complete and verified end-to-end.

## Files written

**`test_helpers/`** (3,080 lines) — `types.py` (12 entity TypedDicts + 20 enums), `api_client.py` (64 endpoint methods), `api_errors.py` (42 error IDs + HTTP map registered with the framework), `assertions.py` (12 per-entity assertions + both ledger-conservation checkers + instant/percentage helpers), `factories.py`, `constants.py`, `test_users.py` (5 roles; per-instance builders for the two `entity_backed:Student` roles), `fixtures.py` (1,524 lines: ~50 primitives, a parameterized `setup_petitioning_election` engine, and ~25 named scenario builders), `__init__.py`.

**`test_suite/`** (3,608 lines) — `conftest.py` + 9 domain-named test files (`test_01_election_records_and_envelope` ... `test_09_access_control`).

## Counts

- **93 tests**, all tagged with exactly one `Design:` line, every tag resolving to a real instance in the correct rule/section.
- **Queue A (difficulty): 19/19 instances x 2 tests = 38** — no shortfalls.
- **Queue B (corner): 55/55 non-stub instances x 1 test = 55** — no gaps. The 14 `excluded_because:` stubs were verified to cross-reference resolvable instances and were not translated.
- **185 PRD citations**, each machine-checked to survive a whitespace-normalized literal grep of `PRD.md`. No `skip`/`skipif`/`xfail`; no scaffold references in emitted code.

## Verification

Ran the suite against the existing `workspace/implementation` under `prd-bench-local-run --isolation per-test-server` (fresh server + empty DB before each test): **93/93 passed** in 117s.

## Instances skipped / trimmed

- **No instance was skipped in full.**
- **One assertion dropped** — `Corner/calculations/registrar_hold_rescores_verified_signature_and_marks_candidacy_deficient`. Its distinguishing aspect also claims the candidacy drops `ELIGIBLE -> PETITION_DEFICIENT` after a registrar sync. **Reason: non-unique-derivability.** PRD §3.1 routes a registrar sync to "the mechanism ... described in Section 3.3", but §3.3 introduces the deficiency hop strictly inside the *voiding* cascade ("Voiding a verified signature can knock a whole slate off its feet... The second hop fires when the recomputed..."). Two PRD-only readers diverge here — and empirically did: the first run failed only on that assertion, with the implementation re-scoring the signature but leaving the candidacy `ELIGIBLE`. The instance's primary effect (verdict flips to `INELIGIBLE_HOLD`, `valid_count` 1->0, `ineligible_count` 0->1, total conserved) is fully asserted; only the secondary cascade hop was omitted, per the `cross-entity-cascade` silence category, with the omission noted in the test's docstring.

**PRD gap surfaced for upstream**: §3.3's three-hop cascade is written as a consequence of `POST /petition-signatures/{id}/void` only; if the registrar-sync path is meant to fire hops 2 and 3 as well, §3.1 or §3.3 needs a sentence saying so.

**Orchestrator verification:** 93 `def test_` across 9 files; 93 `Design:` tags — exact 1:1, no untagged or dual-tagged tests.

## Step 7: Run tests and iterate — 2026-08-17T14:52:00.000Z

The 8-round parallel stability sweep passed clean on the first iteration. No flakiness, no race, no fixture-ordering luck surfaced.

## Result

**Iterations run: 1.** All 8 concurrently-launched rounds reported `93/93 passed, 0 failed, 0 errors, 0 skipped`. The union of failing tests across all rounds is empty, so the diagnostic protocol (STEP 0–3) was never entered.

Verification I did beyond reading the pass counts, since a green number is exactly what the sweep exists to distrust:
- All 8 `results.${i}.json` collected the **same 93 test node IDs** — no round silently under-collected, which would have inflated a `passed == total` ratio.
- `skipped == 0` and `errors == 0` in every round; no `skip`/`xfail`/`skipif` marker exists anywhere in `test_suite/` or `test_helpers/`.
- 93 `def test_` functions across the 9 files matches the 93 collected — no test was shadowed or deselected.
- Each round claimed a distinct port from the runner's registry (e.g. 48777, 50153) with up to 6 concurrent holders; no port collision, no server-restart failure, no retry, no boot timeout in any round's log. Rounds ran 119.5s each with ~121s wall time total, confirming genuine concurrency rather than accidental serialization.

**Why this suite is not timing-sensitive** — the structural reason the sweep was clean, which is the part worth trusting:
- `test_suite/` and `test_helpers/` contain **no threads, no barriers, no `time.sleep`, and no wall-clock reads**. The two "race" tests (`test_ballot_creation_with_a_stale_election_version_is_refused` in `test_suite/test_05_ballot_construction.py` and `test_slate_membership_with_a_stale_candidacy_version_is_refused` in `test_suite/test_03_campaign_finance.py`) exercise the two OCC guards **sequentially** by replaying a captured stale version, so there is no detection window to miss.
- The one plausible nondeterminism vector in a logical-clock system — entities sharing an identical `created_at` and tie-breaking on a random UUID — is closed in the implementation. `workspace/implementation/db.py:158` sorts on `(created_at, _seq)` and `calc.py:286` ranks on `(-certified_votes, -valid_signatures, created_at, _seq)`, both using a monotonic insertion counter rather than `id`. Ties therefore resolve identically on every run.
- `app.py` serializes every request under a store-wide lock acquired in `before_request` and released in `teardown_request`, so no reader can observe a half-applied cascade.

**Changes made: none.** No test was deleted (no PRD-silence or unique-derivability collapse was reached, since nothing failed), no `test_helpers/` fixture was edited, and no `implementation/` file was touched. `git status` confirms zero modifications to tracked source.

One note on artifacts: the sweep's `results.1.json` ... `results.8.json` are left in `workspace/implementation/` as the runbook directs. I removed the per-round stdout logs I had added there so the implementation directory carries nothing beyond its source and the sanctioned results files.

The prior sequential 93/93 was not a lucky round — it reproduces 8-for-8 under ~8x concurrent load.

**Orchestrator verification:** re-parsed all 8 `results.N.json` independently — every round `passed=93 total=93 failed=0 errors=0 skipped=0`. `implementation/` contains only source, `start.sh`, `requirements.txt`, `__pycache__`, and the 8 sanctioned results files.

## Step 8: Finalize PRD — SKIPPED — 2026-08-17T14:53:00.000Z

Skip condition met per the pipeline spec: Step 7 exited on its first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond baseline. With an empty `<step_7_diff>` there is no fix site for Step 8 to trace an edit to, so `PRD_FINALIZED.md` is not produced and Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-17T15:05:00.000Z

Done. `PRD_COMPLETED.md` is written.

## Summary

**Files**: `workspace/PRD.md` (454 lines / 98,386 bytes) -> `workspace/PRD_COMPLETED.md` (454 lines / 104,236 bytes), **char delta +5,850**. Line count unchanged — every change is an in-paragraph insert or revision; no new sections, no new paragraphs, endpoint table (64 rows) and error catalogue (42 rows) untouched.

**Counts**: 41 edited passages — **32 ambiguity-pins**, **9 mismatch-revisions**.

### All three flagged leads confirmed and pinned
- **Registrar sync**: `routes/students.py:104` calls only `calc.recompute_petition_counters`; `cascades.petition_void_cascade` is reachable *only* from signature void (`routes/petition_signatures.py:141`). Hops 2 and 3 do **not** fire on a sync.
- **`invalidated_votes_count`**: `cascades.py:169-170` sums over *every* office candidacy whose `status == "DISQUALIFIED"`, not only STEP 4's own victims — a genuine PRD mismatch.
- **STEP 4 / `ballot_integrity_status`**: `cascades.flag_ballot_integrity` is called only from `compliance_cascade` (`cascades.py:73`); the tally sweep never writes it.

### Changes

**Mismatch-revisions (9)**
- §3.1 — revise — mismatch — registrar sync runs hop 1 only; no `PETITION_DEFICIENT` drop, no slate suspension — `routes/students.py:171-184`
- §3.2 — revise — mismatch — petition `return` `reason` is mandatory and stored nowhere — `routes/candidacies.py:190`
- §3.2 — revise — mismatch — withdrawal `reason` accepted but not persisted; phase breach is `ERR_INVALID_STATE` — `routes/candidacies.py:243,250`
- §3.3 — revise — mismatch — signature-void `reason` not persisted; phase breach is `ERR_INVALID_STATE` — `routes/petition_signatures.py:128,133`
- §3.4 — revise — mismatch — expense-reversal `reason` not persisted, and it *does* have a precondition (`REPORTED`/`APPROVED`) — `routes/campaign_expenses.py:305,308`
- §3.5 — revise — mismatch — case-dismissal `reason` not persisted — `routes/compliance_cases.py:102`
- §3.8 — revise — mismatch — STEP 5 `invalidated_votes_count` spans every `DISQUALIFIED` candidacy of the office — `cascades.py:169`
- §3.8 — revise — mismatch — STEP 6 moves no candidacy `status`; winners are only seated by the certification arm — `cascades.py:186-205`
- §3.8 — revise — mismatch — arm B leaves `DECIDED` offices' candidacies `ON_BALLOT`; winners were *not* resolved during the tally — `cascades.py:300-312`

**Ambiguity-pins (32)**
- §2.3 — insert — ambiguity — filters match by exact equality; `round` coerced to int, non-int matches nothing; unknown params ignored — `listing.py:16-35`
- §2.6 — insert — ambiguity — one `version` bump per request however many times a row is touched; a no-op write still moves the addressed row — `db.py:124-141`
- §3.1 — insert — ambiguity — duplicate `student_number` -> `ERR_INVALID_REQUEST` — `routes/students.py:118-121`
- §3.1 — insert — ambiguity — `required_signature_count` non-negative — `routes/offices.py:28`
- §3.1 — insert — ambiguity — `required_training_modules` non-negative — `routes/offices.py:39`
- §3.2 — insert — ambiguity — filing with a leader recomputes the joined slate's `spending_committed_cents` — `routes/candidacies.py:127-128`
- §3.2 — insert — ambiguity — `slate_leader_candidacy_id` mandatory but explicitly nullable (clears membership) — `routes/candidacies.py:272-276,291`
- §3.4 — insert — ambiguity — venue attrs on a non-`EVENT` line -> `ERR_INVALID_REQUEST` — `routes/campaign_expenses.py:188-191`
- §3.4 — insert — ambiguity — quiet period inclusive at both endpoints; no window set => check passes — `routes/campaign_expenses.py:209-211`
- §3.4 — insert — ambiguity — `poster_count` is a persisted candidacy counter starting at zero — `routes/candidacies.py:115`, `calc.py:140`
- §3.5 — insert — ambiguity — case filing is ungated on candidacy posture and election phase — `routes/compliance_cases.py:22-51`
- §3.5 — insert — ambiguity — uphold requires the case still `FILED`; either breach `ERR_INVALID_STATE` — `routes/compliance_cases.py:79-83`
- §3.5 — insert — ambiguity — hop 2 leaves a respondent in any posture other than `ELIGIBLE`/`ON_BALLOT` untouched — `cascades.py:65-66`
- §3.6 — insert — ambiguity — `approval_threshold_pct` domain 0.00–100.00 — `routes/referenda.py:145-147`
- §3.6 — insert — ambiguity — review `return_reason` is an optional field — `routes/referenda.py:220`
- §3.6 — insert — ambiguity — ballot-create round/form mismatch, wrong election status, and non-`DRAFT` incumbent all `ERR_INVALID_STATE` — `routes/ballots.py:44-64`
- §3.6 — insert — ambiguity — line `position` counts sibling lines in any status, `VOIDED` included — `routes/ballots.py:152-157`
- §3.6 — insert — ambiguity — publish preconditions all `ERR_INVALID_STATE` — `routes/ballots.py:260-267`
- §3.7 — insert — ambiguity — `round` required positive int, never compared to `current_round`; source-state/ballot checks `ERR_INVALID_STATE`; opens>=closes `ERR_INVALID_REQUEST` — `routes/elections.py:113-127`
- §3.7 — insert — ambiguity — opening the polls recomputes `ballots_cast_count`/`turnout_pct` for the opening round (runoff resets to 0 / 0.00) — `routes/elections.py:144`
- §3.7 — insert — ambiguity — mark shape discriminated by the `office_id` / `referendum_id` key; neither => `ERR_INVALID_SELECTION` — `routes/votes.py:71-102`
- §3.7 — insert — ambiguity — `X-User-ID` must resolve to a `Student` row or `ERR_VOTER_INELIGIBLE` — `routes/votes.py:45-47`
- §3.7 — insert — ambiguity — vote-void phase breach `ERR_INVALID_STATE` — `routes/votes.py:149-151`
- §3.7 — insert — ambiguity — close-voting clock short of `voting_closes_at` -> `ERR_INVALID_STATE` — `routes/elections.py:158-160`
- §3.8 — insert — ambiguity — snapshot ballot = most recently created non-`VOIDED` ballot of `current_round` — `cascades.py:94-100`
- §3.8 — insert — ambiguity — STEP 4 stamps `disqualified_reason`, voids lines, decrements `active_line_count`, but never raises `ballot_integrity_status` — `cascades.py:137-147`
- §3.8 — insert — ambiguity — STEP 6 settles every office; no `ON_BALLOT` candidacy => `RUNOFF_REQUIRED` — `cascades.py:199-205`
- §3.8 — insert — ambiguity — STEP 5 raw counts written for every candidacy of the office whatever its status — `cascades.py:163-182`
- §3.9 — insert — ambiguity — `RECOUNT` applies only out of `CERTIFIED`; otherwise a no-op with the appeal still sustained — `routes/appeals.py:251-252`
- §3.9 — insert — ambiguity — `REINSTATEMENT` without a cited case -> `ERR_INVALID_STATE` — `routes/appeals.py:265-267`
- §3.9 — insert — ambiguity — `record-training` requires `transition_status` `PENDING` (`ERR_INVALID_STATE`); `modules_completed` non-negative int — `routes/candidacies.py:312-318`
- §3.9 — insert — ambiguity — activation: election phase -> `ERR_ELECTION_PHASE_INVALID`, term-start -> `ERR_INVALID_STATE` and tested *after* the training check — `routes/candidacies.py:340-350`
- §3.9 — insert — ambiguity — checkpoint requires `CERTIFIED` (`ERR_INVALID_STATE`); delinquent set fixed at sweep head so a promoted alternate is never lapsed in the same request — `routes/elections.py:205-207`, `cascades.py:324-336`

**Orchestrator verification:** both files 454 lines; heading structure byte-identical (no sections added or removed); table rows 110 vs 110 (endpoint + error catalogues untouched); 36 changed lines total — confirms a minimal in-paragraph patch.

---

# Pipeline complete — 2026-08-17T15:05:00.000Z

All 9 steps done (Step 8 skipped by its documented skip condition). Final state: 93/93 tests passing across 8 concurrent stability rounds; `PRD_COMPLETED.md` is the ambiguity-free contract.
