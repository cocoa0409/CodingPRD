# Worklog — task_0919_transitional_care_readmission

Scenario (verbatim):
> 919. Transitional Care & Readmission Program: discharge referral & risk score, 48-hour follow-up call & TCM visit, medication reconciliation, appointment & barrier resolution, red-flag & escalation, 30-day tracking & readmission, TCM-code billing, handoff

Difficulty: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-03T17:27:10.000Z

Created `tasks/task_0919_transitional_care_readmission/` and `workspace/`. Index 0919 = highest existing (0918) + 1.

## Step 3: Copy shared files — 2026-08-03T17:27:12.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0919_transitional_care_readmission/workspace/INSTRUCTION.md` (1424 bytes). Done early alongside Step 1 since it has no dependency on Step 2.

## Step 2: Generate scaffold — 2026-08-03T18:46:30.000Z

All three files are written, parse cleanly, and the linter is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     16
  §1.8 instances scanned:     25
  §1.9 instances scanned:     52
  Calls scanned (§1.8+§1.9):  1027

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Structural totals

| Dimension | Count |
|---|---|
| Entities | **16** |
| Endpoints | **70** |
| State machines | **13** — all 13 non-linear (6 cyclic, 6 branching with divergent side-effect sets, 1 parallel axis) |
| Calculations | **18**, of which **6 dual-variant** (`readmission_risk_score`, `contact_deadline_at`, `visit_due_date`, `tcm_claim_code_selection`, `tcm_claim_net_payable`, `navigator_workload_score`) |
| Error codes | **34** (all 34 triggered by at least one design instance) |
| Validation ladder rungs | **34** (priority 9 is the global record-freeze write gate) |
| OCC rules | **3**, on distinct entities: CareEpisode, MedReconciliation, TcmVisit |
| Conservation invariants | **3**: med-rec bucket total, episode readmission-event total, program-wide navigator active-episode total |
| Deepest cascade | **5** (readmission → episode → claim → record_posture → handoff/red-flag/barrier) |
| Declared constants | **95**, **0 undeclared** (verified by ALL_CAPS token sweep against `domain_constants`) |
| §1.8 / §1.9 instances | 25 across 9 rule_ids / 52 (41 recipes + 11 `excluded_because` stubs) |

YAML parse confirmed for all three files; forbidden concurrency vocabulary absent; `scaffold_difficulty_design`/`scaffold_corner_design` do not appear in `SCAFFOLD.yaml`.

## Reachability / hittability defects found and fixed

1. **`ERR_APPEAL_LIMIT_REACHED` unreachable.** Adjudicating DENIED at the appeal cap went straight to `DENIED_FINAL`, so `DENIED` with `appeal_count == 2` never existed. Moved `DENIED_FINAL` onto the over-limit *appeal attempt* (flip-then-reject, the same device already used for handoff expiry). The DENIED→APPEALED→DENIED cycle now traverses exactly twice and the third appeal both closes the claim and returns the error.
2. **DOWNGRADED claim variant unsubmittable.** `episode.visit_timely == true` was a submit precondition, but a downgraded claim is *defined* by a late visit. Removed that precondition — the code downgrade is the sole handling of day-8-to-14 visits.
3. **`ERR_CLAIM_NOT_BILLABLE` unreachable.** `billing_eligible == false` always co-occurs with a FROZEN episode, which pre-empts at rung 9. Re-scoped the error to "episode has no COMPLETED + ATTESTED visit" — reachable and now tested.
4. **`record_posture: FROZEN` was terminal**, leaving a retracted readmission's episode permanently unusable and making the retraction only a partial compensation. Added the `FROZEN → OPEN` re-evaluation edge, reachable only via retraction out of `CLOSED_READMITTED`; BILLED/ADMIN_CLOSED freezes stay permanent.
5. **`ERR_BLOCKING_DISCREPANCY_UNRESOLVED` masked at attest** (completion already forced `blocking_unresolved_count == 0`). Pinned that discrepancy *reopen* is legal while the parent reconciliation is COMPLETED and does not change the parent's status, making the blocking state reachable post-completion.
6. **Untested-but-declared state** `CareEpisode.BILLED` — added a corner instance driving adjudicate→PAID→BILLED→FROZEN.
7. **YAML syntax traps** hit and fixed: list-indexed capture JSONPaths in flow mappings (`$.data[0].x` → quoted) and `grounds: [...]` flow sequences containing `{`/`[` (converted to block sequences).

Constant hittability was checked for every threshold; both sides are constructible for all of them (risk-tier 31/32, withhold tier 22144/16360, day-30/31/0 readmission, 239/240-minute cooldown, +19/+20-minute calendar buffer, day-7/day-14 visit fork, exact-`sla_due_at` vs +1s barrier breach, cap-2 COUNT vs WEIGHTED workload).

**Orchestrator independent verification (Step 2):** all 3 files `yaml.safe_load` OK (3676 / 2373 / 3388 lines); SCAFFOLD.yaml has neither design key; counts confirmed 16 entities / 70 endpoints / 13 SMs / 18 calcs / 34 errors / 34 validations / 3 concurrency_rules; 6 calcs carry `variants: 2`. Independent ALL_CAPS sweep: 193 tokens, 95 match `domain_constants`, 34 are error ids, remaining 64 are all enum members/status values plus the `ERR_XXX` placeholder inside the §1.0 response-envelope template — **0 undeclared constants confirmed**.

## Step 4: Generate PRD — 2026-08-03T19:02:20.000Z

PRD generated and audited.

**Output:** `workspace/PRD.md` — **487 lines**, written in 12 bounded append operations (sentinel-anchored `Edit` calls), never a single giant write. The file ends with the last row of the §5 Error Code Catalogue (`ERR_NAVIGATOR_CAP_EXCEEDED | 409`) as intended — no audit footer, no contract-report block.

**Audit results**

**Constant coverage: 95 / 95 declared constants covered.** Verified mechanically with a per-constant regex probe (one probe per `domain_constants` key, asserting the concrete value *plus* its disambiguating context, not just a bare numeral). Zero missing. Examples of what the probes pin: `1 for a SEVERE episode` vs `2 for LOW, MODERATE and HIGH`; `TRANSPORTATION carries an sla_hours of 48, is owned by CareNavigator`; `0.03 when net_before_withhold_cents is at least 20000`; `trailing turnaround buffer of 20 minutes`.

**Error-code coverage: 34 / 34.** All 34 appear in the §5 table with their HTTP status, and all 34 also appear in §2/§3 narrative prose paired with the condition that raises them (verified by a separate grep restricted to the text *before* §5).

**Contract 1 — field-name coverage: PASS.** 161/161 `entities[].fields`, 66/66 request-body and structured-output identifiers, 24/24 query params, 16/16 path params — 0 missing. (First run reported false negatives because the ```json fences in §2.2 broke inline-backtick pairing; re-run with fenced blocks stripped.)

**Contract 3 — §3 path purity: PASS.** 1033 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. No fuzzy/approximating words anywhere in the document.

**§2.2** is byte-identical to `section-2.2-response-structure.md`.

**Structure:** 11 §2 subsections (domain-derived: logical clock & holiday set, record posture as global write gate, counter conservation, a full 34-rung ordered validation ladder in §2.10) and 9 §3 subsections organised by episode lifecycle. All 13 state machines' transitions are rendered as explicit state pairs; all 18 calculations including the 6 dual-variant forks are rendered with their fork condition, evaluation order and rounding order in prose (per-component-before-summation for points; rounding at steps 1, 2 and 5 for money); all 3 OCC rules name write endpoint + `expected_<parent>_version` + `ERR_STALE_VERSION`/412; all 3 conservation invariants and the 5-hop unplanned-readmission cascade are stated.

**One under-specified point I had to pin:** the handoff-respond precondition `X-User-ID == handoff.to_navigator_id` carries no error id in the scaffold (respond is deliberately excluded from validation rung 8, since the recipient is by construction *not* the episode's current navigator). I pinned it to `ERR_NOT_EPISODE_OWNER` (403) explicitly in §3.7 rather than leaving it silent, so the downstream test generator and the implementer agree.

**Confirmed: neither design yaml was opened, grepped, or referenced.** Only `SCAFFOLD.yaml`, the skill spec, `section-2.2-response-structure.md`, `example-prd.md` (headings only), and the task's own `INSTRUCTION.md` were read. No sibling task directory was accessed.

**Orchestrator independent verification (Step 4):** 487 lines. All 34 `errors[].id` present in PRD.md. All 70 `endpoints[].path` strings present verbatim. Constant sweep: 92/95 values matched verbatim on the first pass; the 3 apparent misses were confirmed false negatives on manual read — `LOS_OBSERVATION_HOURS_PER_POINT: 12.0` is rendered as "divided by 12", and `MONEY_ROUNDING`/`POINTS_ROUNDING` are rendered as the prose "rounded half up to whole cents" / "rounded half up ... applied per component before summation". **95/95 effective.** No design-yaml vocabulary (`test_recipe`, `excluded_because`) leaked into the PRD.

## Steps 5 + 6: Unit tests and implementation (launched concurrently in one message) — 2026-08-03T19:31:40.000Z

### Step 5 — unit tests

**`test_helpers/`** (9 files, ~1,770 lines) — `types.py` (16 entity TypedDicts + 15 status enums), `api_client.py` (all 70 endpoints, one method each), `api_errors.py` (34 error IDs registered with the framework status map), `assertions.py` (per-entity assertions + the two conservation checkers + `parse_instant`/`assert_same_instant`), `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (~520 lines, 6 tiers up to `setup_submitted_claim`).

**`test_suite/`** (conftest + 10 domain-named files, ~3,700 lines).

**Counts**
- **Test count: 102** (50 queue-A + 52 queue-B).
- **Queue A: 25/25 instances covered**, every one by exactly 2 tests.
- **Queue B: 52/52 non-stub instances covered**, 1 test each. The 11 `excluded_because` stubs were not translated; all 11 `difficulty_instance` cross-references were verified to resolve to real queue-A instance names.
- **Instances SKIPPED: none.** Every non-stub instance passed the PRD-first two-condition filter — the PRD names each asserted `error_id`, threshold and transition verbatim (the ordered intake gauntlet, the two OCC loci, the sweep phase counters, the strict-vs-inclusive boundaries and the money waterfall are all stated explicitly in prose, not only in the §5 table).

**Self-checks (all pass)**
- **(a)** 102 `def test_` functions, 102 `Design:` tag lines, exactly one per test, counts equal.
- **(b)** No `skip`, `xfail` or `skipif` anywhere in `test_helpers/` or `test_suite/`.
- **(c)** `python3 -m py_compile` succeeds on all 20 emitted `.py` files; `pyflakes` clean; `pytest --collect-only` collects 102.
- **(d)** Every tag resolves to a real `name:` in the corresponding yaml; no test tags a stub.

Two extras worth noting: all 176 PRD citations were machine-verified as verbatim substrings of `workspace/PRD.md` after whitespace normalisation (one non-verbatim quote was found and corrected), and a grep confirms **zero** raw string equality on any of the 22 instant-valued fields — every timestamp assertion routes through `assert_same_instant`, which tolerates both `…Z` and `….000Z` renderings. Every deadline/SLA test drives time through `POST /_clock/set_current_utc`, and every `CareNavigator` call is issued with `make_care_navigator_headers(<real Navigator.id>)` so ownership, handoff-recipient and segregation-of-duties identities are distinct where the PRD requires it.

### Step 6 — implementation

**Deliverable: 22 files, 3,350 lines** (20 Python modules + `start.sh` + `requirements.txt`). Layered: `store.py` (in-memory dicts, logical clock, temporal/rounding helpers), `constants.py` (all 95 declared domain constants), `errors.py` (34-code catalogue), `envelope.py`, `guards.py` (ladder rungs 1–9), `domain.py` (18 calculations, 3 conservation recomputations, freeze cascade), and 12 route blueprints.

**Completeness gate: declared 70 / registered 70 / MISSING 0 / EXTRA 0** (plus Flask's own `/static`). Path params were normalized on both sides before diffing.

**Bug (a) — timestamp rendering: ONE uniform rule.** **Every instant this API renders is formatted `YYYY-MM-DDTHH:MM:SS.mmmZ` — exactly three fractional digits, trailing `Z` — regardless of how the caller wrote it.** Instants are stored internally as `datetime` objects and formatted only at serialization (`store.fmt_instant`), so there is no second code path. This covers all four categories: (i) `created_at`/`updated_at`/`api_request_timestamp`; (ii) every server-written stamp off the logical clock (`referred_at`, `attempted_at`, `assessed_at`, `opened_at`, `closed_at`, `raised_at`, `acknowledged_at`, `completed_at`, `attested_at`, `disposition_at`, `proposed_at`, `responded_at`, `paid_at`, `successful_contact_at`, `visit_completed_at`); (iii) arithmetic-derived instants (`contact_deadline_at`, `sla_due_at`, `ack_due_at`, `expires_at`, end-of-day deadlines rendered `T23:59:59.999Z`); (iv) caller-supplied instants echoed back (`discharge_datetime`, `scheduled_start`, `scheduled_end`) — these are re-rendered in canonical form, not echoed verbatim. Authority: PRD §2.4 names all of those fields and states they "are ISO 8601 UTC timestamps with exactly three fractional-second digits and a trailing `Z`", and §2.5 says the same of `created_at`/`updated_at`. **Judgement call:** `current_utc` on `POST /_clock/set_current_utc` is *not* in §2.4's enumeration; I render it with the same rule (`2026-05-14T09:00:00Z` in → `2026-05-14T09:00:00.000Z` out) rather than echoing the operator's literal string, because §2.4 is the document's only normative format statement and the instruction asks for one consistent rule. This is the single place where a plain-`Z` expectation would diverge.

**Bug (b) — enum-membership routing: ONE consistent rule.** PRD §2.10 rung 4 gives a **closed, explicitly exhaustive list** of body fields that route to `ERR_INVALID_ENUM`, ending "No other field routes to this error." The rule implemented is therefore: **a closed-set body field raises `ERR_INVALID_ENUM` (400) if and only if it appears in that rung-4 list; every other closed-set field's membership violation is a rung-3 `ERR_VALIDATION` (400).** All 24 listed field/endpoint pairs go through `guards.enum()`; the one closed-set field deliberately excluded from the list — `closure_reason_code` on referral closure — goes through `guards.validation_enum()` and yields `ERR_VALIDATION`. Because rung 3 precedes rung 4, presence/type checks (and `closure_reason_code` membership) fire before any enum-membership check; verified: `{outcome:"NOPE", closure_reason_code:"OTHER"}` → `ERR_INVALID_ENUM`, `{outcome:"DENIED", closure_reason_code:"NOPE"}` → `ERR_VALIDATION`.

**Verification.** Three smoke suites (~180 assertions) all pass, covering both PRD worked examples exactly: risk score 12/6/18/11/8 = 55 → SEVERE; both money waterfalls (99496 → 27680/5536/22144/0.03/664/21480 and 99495 → 20450/4090/16360/0.01/164/16196, including the withhold-tier flip); both contact-deadline variants (`2026-05-05T23:59:59.999Z` vs `2026-05-03T14:00:00.000Z`); the 5-rung intake gauntlet in order; the 20-minute trailing-buffer boundaries (19 min conflicts, 20 min does not); the modality ladder + 240-min cooldown; medrec conservation with the "COMPLETED recon + reopened CRITICAL item re-blocks attestation" state; all 3 OCC rules; the 3-phase sweep (escalate → promote → breach, with phase-1 flags immune to phase-2); the 5-hop unplanned-readmission cascade to `FROZEN` plus retraction thaw; both stateful-rejection rungs (32 persists `DENIED_FINAL`, 33 persists `EXPIRED`); and both weighted/count cap policies.

**Fresh boot confirmed:** `bash start.sh` binds `0.0.0.0:$PORT` in the foreground and answers within ~1s; killing and re-launching resets the clock to `2026-05-01T00:00:00Z` and empties every table (re-registering a previously-used unique MRN returns 201). **No seeded data, no on-disk persistence** — a grep for `sqlite|open(|json.dump|pickle|shelve|/tmp|seed_` across all sources returns nothing; storage is Python dicts in `store.DB` only.

Two spots where the PRD is silent and impl chose deliberately, flagged for Step 9: the data-driven `ERR_FORBIDDEN_ROLE` checks (barrier-close owner/waiver, red-flag tier routing) run after existence resolution but **before** the rung-9 freeze gate; and appending a discrepancy to a `COMPLETED` reconciliation is **allowed** (the PRD states parent-status gates for disposition and reopen but not for append).

**Orchestrator independent verification (Steps 5+6):** booted the app in-process and diffed `app.url_map` against `SCAFFOLD.yaml endpoints[]` with path params normalized on both sides — **declared 70 / registered 70 / MISSING 0 / EXTRA 0**, confirming the Step-6 gate. `def test_` count == `Design:` tag count == **102**. `grep -rn '@pytest.mark'` over `test_suite/` + `test_helpers/` returns **nothing** (the `skip` grep hits are the English words "skips"/"skipped" inside docstrings and one test function name). Persistence grep over `implementation/*.py` for `sqlite|json.dump|pickle|shelve|/tmp` returns nothing.

Pre-staged `workspace/sweep.sh` for Step 7 (8 rounds as 2 waves of 4, `SWEEP_DONE` marker, no inline pkill).

## Step 7: Run tests and iterate — 2026-08-03T19:52:00.000Z

Clean sweep: all 8 rounds 102/102.

**Iterations run:** 2 (baseline sweep, one fix, confirming sweep).

**Baseline:** 101/102 in all 8 rounds — a single, fully deterministic failure (not flaky): `test_sweep_expires_a_stale_proposal_and_the_later_response_is_rejected` in `test_09_handoff_and_navigator_workload.py`, asserting `ERR_HANDOFF_EXPIRED` but getting `ERR_INVALID_STATE`.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none. (Notably, the two adjudication points flagged at generation were both non-issues: no test does raw string equality on an instant — every comparison already routes through `assert_same_instant`/`parse_instant` in `test_helpers/assertions.py` — and no test contradicted §2.10 rung 4's exhaustive `ERR_INVALID_ENUM` list.)

**Fixes applied to `test_suite/`:** one, in `test_suite/test_09_handoff_and_navigator_workload.py`, `test_sweep_expires_a_stale_proposal_and_the_later_response_is_rejected` — relaxed the final rejection from `validate_error(ERR_HANDOFF_EXPIRED)` to `validate_error_is_one_of([ERR_HANDOFF_EXPIRED, ERR_INVALID_STATE])`, the STEP 1b **ERROR PRECEDENCE SILENCE** case (scaffold rule `Corner/endpoints/sla_sweep_phase3_expires_stale_handoff_and_response_is_rejected`).

Why it is not uniquely derivable: the sweep has already moved the row out of `PROPOSED` before the response arrives. PRD §2.10 rung 10 ("The target resource is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE`") precedes rung 33 ("The current instant is on or before the handoff's `expires_at` — otherwise `ERR_HANDOFF_EXPIRED`... Applies to responding to a handoff"), and that ordering is explicitly normative — "an implementation that reports a later rung's error where an earlier rung also failed is wrong". The §3.7 sentence the test cites describes the flip as `PROPOSED → EXPIRED`, so it speaks only to a row still in `PROPOSED` and is silent on an already-`EXPIRED` one. Both implementations are articulable from the PRD, so PRD supports the "`ERR_HANDOFF_EXPIRED` is possible" reading and the permitted relaxation applies rather than deletion.

Every other assertion in the test was kept, and one was **added** (`status` is still `EXPIRED` after the rejected response), so the test is net stricter on state and looser only on the non-derivable error_id. No skip/xfail was added anywhere; `skipped=0` in all 8 rounds.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful here. `routes/handoffs.py::respond_handoff` correctly implements rung 33's deliberate mutate-then-reject (a `PROPOSED` handoff past `expires_at` is flipped to `EXPIRED`, persisted, *then* `ERR_HANDOFF_EXPIRED` is raised, lines 106–112), with rung 10 gating ahead of it per the ladder. Note that the pure rung-33 path (respond while still `PROPOSED` after expiry) is implemented but has no test exercising it — the suite only reaches expiry via the sweep.

**Final per-round pass/total:** 102/102 x8 — 8/8 rounds clean, 0 failures, 0 errors, 0 skips, all exit 0.

**Orchestrator independent verification (Step 7):** re-parsed all 8 `results.N.json` myself — each has **102 individual rows** (not just an aggregate counter), status distribution `{'passed': 102}`, aggregate `passed=102 failed=0 total=102 skipped=0 errors=0`, and the sorted test-name list is **byte-identical to round 1 in all 7 comparisons** (no round silently collected a smaller suite). `def test_` count in `test_suite/` == 102 == runner's collected count. `@pytest.mark` occurrences: **0**. Persistence grep over `implementation/*.py`: **0** hits.

## Step 8: Finalize PRD — 2026-08-03T20:03:00.000Z

`PRD_FINALIZED.md` written with exactly one edit. (Step 8 was NOT skipped: the skip condition requires 0 fixes of every kind, and Step 7 applied one `test_suite/` assertion relaxation — which is precisely the PRD-silence signal Step 8 exists to pin.)

**Line counts:** `PRD.md` 487 / `PRD_FINALIZED.md` 487 — **0.0% line delta** (1 line revised in place, +4 sentences of prose).

**Change**
- **§2.10 Request Validation Order** (final paragraph, line 179) — *revise* — appended to the existing "two rungs deliberately mutate state" paragraph: once a row has already left the state its transition is declared from (handoff out of `PROPOSED`, claim out of `DENIED`), the request never reaches rung 32/33 and is reported as `ERR_INVALID_STATE` at the rung-10 state gate; names the unattended routes out of `PROPOSED` (sweep phase 3, newer proposal, freeze cascade); and reasserts that earlier rungs still win, with rung 9 `ERR_EPISODE_RECORDS_FROZEN` as the concrete example — `implementation/routes/handoffs.py:104-112`, `implementation/routes/claims.py:188-199`.

**Pre-edit search log**

*(a) Subject identified.* Which error id surfaces when the target row has already been swept/flipped into a terminal state ahead of a "mutate-then-reject" rung — the interaction between the rung-10 state gate and rungs 32/33, plus everything upstream of rung 10 that could pre-empt it.

*(b) Impl paths enumerated (read or grepped, not just the Step 7 site).*
- `routes/handoffs.py::respond_handoff` (Step 7 site) — rung 8 ownership-vs-handoff L101, rung 9 L104, rung 10 `status != "PROPOSED"` L106-107, rung 33 mutate-then-reject L109-112, rung 34 cap L116-119.
- `routes/claims.py::appeal_claim` (parallel mutate-then-reject) — rung 9 L188, rung 10 `status != "DENIED"` L190-191, rung 32 flip to `DENIED_FINAL` + zero `net_payable_cents` + `evaluate_freeze` then raise, L193-199.
- `routes/episodes.py::sla_sweep` phase 3 L155-165 — the unattended `PROPOSED → EXPIRED` route (phases 1/2 read for ordering context).
- `domain.py::freeze_cascade` L350-366 — the other unattended route out of `PROPOSED` (`→ SUPERSEDED`, `superseded_by_id` null); `domain.py::evaluate_freeze` L340-347 and `void_claim` L369-372 for claim-side terminal statuses.
- `routes/handoffs.py::propose_handoff` L55-63 — the third route out of `PROPOSED` (supersede-by-newer-proposal).
- `guards.py::require_open_records` L192-195 and `require_episode_owner` L185-188 — the rung 9 / rung 8 implementations.
- Full grep of every `ERR_INVALID_STATE` and `require_open_records` callsite across `routes/` (barriers, claims, contacts, episodes, handoffs, medrec, readmissions, redflags, referrals, visits) to confirm rung 9 precedes rung 10 at every site the new sentence could be read against — it does at all of them; `readmissions.py:88` retraction is the rung-9-exempt case and the wording does not mention it.
- `constants.py` for claim/handoff status vocabularies; `PRD.md` §2.7 L116/L120, §3.7 L307/L309/L319, §3.8 L341 for existing prose the new sentence must not contradict.
- `test_suite/test_09_handoff_and_navigator_workload.py:228-269` as auxiliary evidence only.

*(c) Wording adjustments made to keep all enumerated paths consistent.*
1. Rejected the first draft's "a response to an already-`EXPIRED` handoff is `ERR_INVALID_STATE`" as too narrow — `freeze_cascade` and `propose_handoff` also move rows out of `PROPOSED`, so it was widened to "already left the state its transition is declared from" with the status list enumerated (`EXPIRED`, `SUPERSEDED`, `ACCEPTED`, `DECLINED`).
2. Added the explicit rung-9 carve-back ("on an episode whose records are frozen … `ERR_EPISODE_RECORDS_FROZEN` before the state gate is ever consulted") because the freeze cascade's `PROPOSED → SUPERSEDED` always coexists with `record_posture == FROZEN`; without it the new sentence would have falsely universalised `ERR_INVALID_STATE` over the freeze path — a brand-new mismatch.
3. Wrote "a further attempt on a claim already in `DENIED_FINAL`" rather than pinning an ordinal, to stay consistent with §3.8's existing wording and with `appeal_count` reaching 2 via either adjudication route.
4. Changed "the rungs above 10" to "the earlier rungs" to avoid the above/below ambiguity in a section where a lower rung number means higher precedence.

## Step 9: Complete PRD — 2026-08-03T20:20:00.000Z

`PRD_COMPLETED.md` written.

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 487 | 491 (+4) |
| chars | 104,656 | 123,322 (**+18,666**) |
| changed hunks | — | 43 edits across 42 paragraph/table lines |

**Counts: 36 ambiguity-pins, 7 mismatch-revisions.** All edits are in-paragraph inserts or rewrites; no new sections.

### Mismatches (PRD said something the impl does not do)

- **§4 endpoint-table preamble** — revise — "creates → 201" made conditional on *answering with the created resource*; `POST /referrals/{id}/accept` mints a `CareEpisode` + `RiskAssessment` yet replies **200 with the referral** — `routes/referrals.py:222`
- **§4 accept table row** — revise — same, stated in the directory row — `routes/referrals.py:222`
- **§2.10 rung 28** — revise — rung tested "the episode has a completed visit"; impl tests **the visit named by `visit_id`** — `routes/claims.py:39`
- **§3.8 claim preparation** — revise — same, in prose ("the presence of some *other* billable visit does not rescue it") — `routes/claims.py:39`
- **§2.10 rung 22** — revise — attestation reads the reconciliation **live**; claim submission reads only the episode's **frozen `medrec_complete`** flag and never re-reads the reconciliation — `routes/claims.py:136` vs `routes/visits.py:208-217`
- **§3.8 prepared-claim fields** — revise — `service_period_start_date` is "copied from the episode", but the episode carries **no such field**; it is taken from `discharge_date` — `routes/claims.py:53`, `routes/referrals.py:158-199`
- **§3.9 administrative closure** — revise — the optional `reason` is validated then **discarded**; no episode field records it — `routes/episodes.py:65`
- **§2.4 clock consequences** — revise — "or by whatever request happens to be evaluated next" implied lazy evaluation; only the handoff-respond path does it, and **no read endpoint ever writes** — `routes/handoffs.py:109`

### Ambiguity pins — version granularity

- **§2.5** — insert — the full rule: one request = one bump per row; rows created by the request stay at 1; the path-named row bumps even when the write changes nothing; roll-up recomputations bump only on an actual value change; mutate-then-reject rungs still bump — `store.py:208-251`, `domain.py:140-148`
- **§2.4 holidays** — insert — an episode reached by the holiday recompute bumps only if the deadline or `contact_timely` actually moves — `routes/reference.py:47-50`
- **§3.2 hop 2/3** — insert — episode bumps unconditionally on re-assessment; every refreshed visit bumps even when nothing changed — `routes/risk.py:44,60`
- **§3.3 logging** — insert — every logged attempt bumps the episode, not just the first — `routes/contacts.py:72`
- **§3.3 disposition** — insert — `NO_ANSWER`/`VOICEMAIL` leave the episode's `version`/`updated_at` untouched — `routes/contacts.py:118-128`
- **§3.4 confirm** — insert — re-confirming an already-`CONFIRMED` visit succeeds and still bumps — `routes/visits.py:106-107`
- **§3.4 complete** — insert — completion bumps the episode by 1 — `routes/visits.py:137`
- **§3.8 prepare** — insert — episode bumps; claim answers 201 at version 1 — `routes/claims.py:96`

### Ambiguity pins — timestamps & envelope

- **§2.2** — insert — `api_request_timestamp` is read from the **logical clock**, so it repeats verbatim within a logical instant; `api_request_id` is `req_` + 20 upper-alnum chars — `envelope.py:13,19`
- **§2.4 instant list** — insert — `current_utc` and `api_request_timestamp` added; caller-supplied `discharge_datetime`/`scheduled_start`/`scheduled_end` are **re-rendered canonically**, not echoed — `store.py:85-97`
- **§2.4 clock endpoint** — insert — `data` is exactly `{"current_utc": …}`; input may carry 1–6 fractional digits or a `±HH:MM` offset and is normalised — `routes/reference.py:22`, `store.py:100-128`
- **§2.4 holiday endpoint** — insert — `data` is exactly `{"holiday_dates": […]}`, order preserved, duplicates kept, unsorted; global set has no `id`/`version` — `routes/reference.py:38,52`

### Ambiguity pins — ordering, filters, resolution order

- **§2.3** — insert — list tie-break is **mint order** (never `id`, never a domain date); off-enum/unmatched filter value → empty page, not 400; `is_current` accepts only `true`/`1`/`false`/`0` — `store.py:264-268`, `routes/risk.py:92-98`
- **§2.10 rung 2** — insert — the three data-driven `ERR_FORBIDDEN_ROLE` checks run **after rung 6, before rung 9** — wrong-role beats frozen records and beats the state gate, but 404 still beats them — `routes/barriers.py:76-88`, `routes/redflags.py:55-63`
- **§2.1** — insert — whitespace-only headers count as empty — `guards.py:16`
- **§3.6 sweep** — insert — response `data` is exactly the five counters, an object; rows walked oldest-first by `created_at` + mint order; the sweep is itself gated by rung 9 — `routes/episodes.py:90,102,169-177`

### Ambiguity pins — gate scope / no-op branches

- **§3.5 append** — insert — appending has **no parent-status gate**: legal against a `COMPLETED` reconciliation, which keeps that status while `medrec_complete` stays true — `routes/medrec.py:68-101`
- **§3.5 disposition** — insert — the item's own state is tested before the parent's; both are `ERR_INVALID_STATE`; rung 24 last; omitted `resolution_note` stores null — `routes/medrec.py:138-147`
- **§3.5 reopen** — insert — `resolution_note` and `disposition_at` are **not** cleared — `routes/medrec.py:164-165`
- **§3.5 complete** — insert — non-empty `OPEN` parent and already-`COMPLETED` parent are both `ERR_INVALID_STATE` — `routes/medrec.py:180,185`
- **§3.4 amend** — insert — amendment re-runs **none** of attestation's gates; a stripped element set is stored and only fails at the next attestation — `routes/visits.py:242-250`
- **§3.4 attest** — insert — declared from `DRAFT`/`AMENDED` only; the four gates run in stated order — `routes/visits.py:205-219`
- **§3.4 book** — insert — `navigator_id` may be **any** registered navigator; no episode-status gate; an episode may hold several visits; `visit_completed_at` reflects the latest completion; a slot booked past the due instant opens at `SCHEDULED_LATE`; full initial-field list — `routes/visits.py:36-68`
- **§3.4 complete** — insert — three preconditions in order, all `ERR_INVALID_STATE`; returns the visit — `routes/visits.py:123-128`
- **§3.7 propose** — insert — no episode-status gate; answers 201 with the handoff at version 1 — `routes/handoffs.py:26-66`
- **§3.7 cap gate** — insert — `COMMUNITY_PROGRAM`/`PCP_PROGRAM` still require a **real Navigator** and still reassign `navigator_id` and move both navigators' counters; only the cap is bypassed — `routes/handoffs.py:27,114-127`
- **§3.9 record** — insert — no state gate: legal against any episode status; a second `UNPLANNED_INPATIENT` on a `CLOSED_READMITTED` episode leaves `pre_readmission_status` as-is; 201 with the event, 200 on retract — `routes/readmissions.py:36-40,55`
- **§3.9 retract** — insert — `billing_eligible` returns true unconditionally; `recoupment_required` is **never** cleared — `routes/readmissions.py:100`
- **§2.7 exemption** — insert — the readmission exemption reaches every downstream consequence inside the frozen subtree, not just the event row — `routes/readmissions.py:36-53`
- **§3.8 duplicate claim** — insert — overlap inclusive at both ends; scan covers the same episode's own earlier claims; a replacement may be prepared once the prior is `VOIDED` — `routes/claims.py:15-16,55-61`
- **§3.8 submit** — insert — episode-status and `billing_eligible` failures are `ERR_INVALID_STATE`; six checks in fixed order — `routes/claims.py:128-139`
- **§3.8 adjudicate** — insert — `PAID` also releases navigator/patient open-episode counters; `denial_reason_code` is neither stored nor cleared on `PAID`, and a code-less `DENIED` stores null — `routes/claims.py:169-176`

### Ambiguity pins — derived values & defaults

- **§3.1 episode creation** — insert — the full neutral-value list, `billing_eligible` **true** and the three compliance flags **false** (not null), and that the episode has no `service_period_start_date` — `routes/referrals.py:176-199`
- **§3.1 patient** — insert — `external_mrn` clash is `ERR_VALIDATION` at rung 3; `primary_language` rejects `""` and is stored unvalidated — `routes/reference.py:63-66`
- **§3.1 referral closure** — insert — `closure_reason_code` is required and is a **rung-3** field, so it is reported ahead of an out-of-set `outcome` — `routes/referrals.py:231-233`
- **§3.2 hop 3/4** — insert — hop 3 covers `SCHEDULED` **and** `NO_SHOW`; hop-4 flags carry the **acting navigator's `X-User-ID`** (not `SYSTEM`), null `source_barrier_id`, `ack_due_at` = now + 120 min; a `WEIGHTED` navigator's workload is recomputed; answers 201 with the assessment — `routes/risk.py:52,66-74`
- **§3.3 modality** — insert — declared members are exactly `PHONE`/`SECURE_MESSAGE`/`HOME_VISIT`; off-set → rung-4 enum error before the ladder — `constants.py:60`
- **§3.6 barrier close** — insert — `status` becomes the `outcome` verbatim; five possible barrier statuses — `routes/barriers.py:92`
- **§3.6 red flag** — insert — `ed_event_suppressed` is false on **every** flag from birth; all four null fields listed — `domain.py:394-397`
- **§3.6 acknowledge** — insert — acknowledgement moves neither `open_red_flag_count` nor `escalation_state`, and leaves `ack_due_at` standing — `domain.py:225-239`
- **§3.8 claim fields** — insert — `withhold_pct` is persisted and returned — `domain.py:476-483`

### Areas checked that came back genuinely clean

The PRD already pinned these uniquely; nothing changed:

- **All 6 dual-variant calculations and their rounding order** — per-component half-up rounding before summing, per-component caps, the 60 cap; the 3-multiplication money waterfall rounding each step off the previously rounded figure; the business-days vs calendar-hours contact deadline; the LOS inpatient/observation fork and its asymmetric caps; the `99496`/`99495` code fork and `DOWNGRADED`/`FULL` variant.
- **Every threshold's `<` vs `<=`** — risk tier floors (`>=`), withhold tier at `>= 20000`, contact cooldown inclusive at 240 min, the 20-minute trailing-only slot buffer at both boundaries, barrier breach strictly after `sla_due_at`, red-flag/handoff expiry strictly after, service-period closure strictly after end-of-day, `visit_timely`/`contact_timely` inclusive at the deadline instant, day_index 1–30 inclusive, navigator cap inclusive, intake window `+2` days.
- **The 34-rung ladder's relative precedence** — verified rung-by-rung against every route; every ordering matched, including the rung-10 carve-out for claim preparation and the two mutate-then-reject rungs (32/33) and Step 8's "already left the declared state → `ERR_INVALID_STATE`" note.
- **All 34 error codes and their HTTP statuses** — `errors.py:15-50` matches §5 exactly, one for one.
- **The freeze cascade's three legs** — including `superseded_by_id` left null on the freeze path vs set on the newer-proposal path, `closed_at` stamped on administratively closed barriers, terminal children not restored on thaw, and the fact that the cascade touches nothing else (no visits, attempts, discrepancies, reconciliations or claims).
- **The three OCC rules** — required-integer fields, rung-11 placement, and the fact that no other endpoint accepts or compares a version.
- **The three conservation invariants** — all three are recomputed from the underlying rows on every mutation, so they cannot drift.
- **Pagination** — defaults, 1–100 bounds, non-integer rejection (including `"010"`/`"+5"`/`"1.0"`), `has_more` formula, `total_count` before paging, unknown query params ignored.
- **The intake gauntlet's five rungs and their order**, `IN_NETWORK`/`tcm_covered` checks, and the fact that referral *creation* screens nothing.
- **Barrier type table** (SLA hours, owner role, blocking class) and the **red-flag tier table** (ack minutes, routing role, promotion step, `MAX_REDFLAG_PROMOTIONS`).
- **Sweep phase semantics** — phase-1 sideways unconfirm of `SCHEDULED`+`CONFIRMED` visits, phase-1 flags exempt from phase 2 of the same sweep, promote-vs-breach condition, non-blocking barriers never escalating.
- **Segregation of duties** on both loci, and `ERR_NOT_EPISODE_OWNER` measured against the handoff (not the episode) on `respond`.
- **The `SENT_TO_ED` window** (`discharge_date + 1` .. `readmission_window_end_date`, inclusive) and its `SYSTEM` attribution.
- **Response-field projection generally** — the serializer emits every stored field of every entity with no computed value withheld; the only suppressed key is the private compliance-flag latch, which the PRD never names.

**Orchestrator independent verification (Step 9):** `PRD_COMPLETED.md` is 491 lines and ends on the last §5 catalogue row (`ERR_NAVIGATOR_CAP_EXCEEDED | 409`) — no truncation. All 34 error ids and all 70 endpoint paths still present. All 5 top-level sections intact. `find implementation/ test_suite/ test_helpers/ -name '*.py' -newer results.1.json` is **empty** — no code was touched after the clean sweep, so the 102/102 x8 result still describes the shipped tree. Removed the `SWEEP_DONE` marker from `implementation/`.

## PIPELINE COMPLETE — 2026-08-03T20:22:00.000Z

102/102 tests on all 8 stability rounds. 0 test deletions, 0 implementation fixes, 1 test_suite assertion relaxation.
