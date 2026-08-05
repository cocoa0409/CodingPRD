# Worklog — task_0914_school_based_health_center

Scenario (verbatim): 914. School-Based Health Center: student enrollment & consent, visit (acute/behavioral/dental) & sports physical, immunization & screening, referral & care coordination, sponsor-hospital billing & sliding fee, parent notification, telehealth-to-classroom, reporting

Difficulty target: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-03T14:52:00.000Z

Created `tasks/task_0914_school_based_health_center/` and `workspace/`. Index 0914 = max existing (0913) + 1.

## Step 3: Copy INSTRUCTION.md — 2026-08-03T14:52:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0914_school_based_health_center/workspace/INSTRUCTION.md`. (Run early; no dependency on Step 2.)

## Step 2: Generate scaffold — 2026-08-03T15:51:00.000Z

All three artifacts are written, lint-clean, and parse cleanly.

### Output
- `SCAFFOLD.yaml` (3,500 lines; §1.0–§1.7 + `domain_constants`, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,621 lines; single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (3,281 lines; single key `scaffold_corner_design`)

### Requested metrics
| Metric | Value |
|---|---|
| Entities | **15** (School, Clinician, Student, Guardian, Enrollment, Consent, Visit, SportsPhysicalClearance, ImmunizationDose, Screening, Referral, BillableCharge, ParentNotification, TelehealthSession, AggregateReport) |
| Endpoints | **67** (42 mutating + 25 read; 24 of the reads are the mandated FK reverse-reachability GETs) |
| Error codes | **38** |
| State machines | **11 machines / 12 `state_machines[]` entries** (Visit occupies two parallel axes), 78 transitions |
| Non-linear machines | **9** — School (cyclic), Enrollment (cyclic+capped), Visit (parallel axes × compound bubble-up), SportsPhysicalClearance (cyclic+capped), Referral (capped self-loop), BillableCharge (denial↔appeal cycle), ParentNotification (capped retry self-loop), TelehealthSession (no-show/reschedule cycle) |
| Calculations | **13**, of which **4 dual-variant**: `charge_patient_responsibility` (PROVISIONAL_GROSS_FIRST 1000 vs FINAL_NET_OF_PAYER 1600), `immunization_compliance_status` (GRACE vs STRICT), `clearance_validity_window` (CALENDAR_DAYS 2027-05-10 vs SCHOOL_YEAR_CAPPED 2026-07-31), `referral_closure_rate` (0.5000 vs 0.6667) |
| Validation ladder | **32 rungs** |
| OCC rules | **3** (consent-, enrollment-, clearance-create-stale-student; all on `Student.version`) |
| Max cascade depth | **5** (dose void → successor doses invalid → compliance NON_COMPLIANT → clearance VOIDED → CLEARANCE_VOIDED notification); second chain depth 4 from a screening REFER |
| Declared constants | **64** with explicit values (grep of ALL_CAPS left 0 value-less numeric constants; all remaining ALL_CAPS tokens are enum members, variant names, reason codes, or prose) |
| YAML parse check | **all 3 files parse OK** |

```
Coverage
  §1.5 endpoints declared:    67
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  819

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Design notes worth carrying forward
- §1.8 = 9 rule_ids × 2 = **18 instances**; §1.9 = **56 instances** (51 with full chains + 5 `excluded_because` stubs, all citing existing §1.8 names). All 74 instance names are unique across both files; every `grounds:` ref was machine-verified to resolve into §1.1–§1.7 (0 dangling).
- **Validation-ordering fix during authoring**: `ERR_OUTREACH_LIMIT_EXCEEDED` and `ERR_DELIVERY_ATTEMPTS_EXHAUSTED` would have been permanently masked by the terminal-state check (the attempt that exhausts the cap also drives the row terminal). Rung 16 was inserted *above* the state rung for exactly those two endpoints — which also yields a third genuine priority-conflict pair (business_constraint vs state).
- **Charge-status enum trimmed** (`PATIENT_BILLED` removed) so every declared value has a producing transition; Visit's billing axis treats `REVERSED` as terminal with the all-REVERSED case evaluated first, so the bucket identity survives a compensating reversal.
- All money/date literals in asserts were computed in Python, not estimated: FPL 93.46/151.66/180.09/213.27, tier edge 1560001 → 100.00 → TIER_A (round-then-band), nominal floor 500, provisional 1000 vs final 1600, grace dates 2025-09-25/2025-11-16, clearance 2027-05-10 vs 2026-07-31, rates 0.5000/0.6667.
- Logical clock default is pinned to `2026-05-01T00:00:00.000Z`; school year 2025-2026 (ends 2026-07-31) contains it, so every window rule is run-time independent.

### Orchestrator's independent verification
- `yaml.safe_load` on all 3 files: OK. Top-level keys of SCAFFOLD.yaml: scenario, domain_name, api_prefix, complexity_profile, response_envelope, domain_constants, entities(15), state_machines(12), concurrency_rules(3), calculations(13), validations(32), endpoints(67), errors(38), roles(7).
- Independent ALL_CAPS sweep: 64 declared constants; 154 residual tokens, **all** enum members / variant names / reason codes / prose (`DISCOUNT_PCT_TIER_` was a regex artifact of the declared `DISCOUNT_PCT_TIER_{A..E}` family). **0 undeclared constants.**

## Step 4: Generate PRD — 2026-08-03T16:05:00.000Z

The PRD is complete at `workspace/PRD.md` (14,309 words; §1 Introduction → §2 with 10 subsections → §3 with 12 domain subsections → §4 endpoint table → §5 error table, no audit footer).

### Self-audit

**(a) Endpoints: 67/67.** Programmatic diff of the §4 table against `endpoints[]` returns an empty symmetric difference — every method+path pair matches exactly, with the scaffold's `roles` list reproduced per row.

**(b) Error codes: 38/38.** All 38 appear in the §5 table *and* all 38 also appear in §2/§3 prose attached to their trigger condition (the §5 table itself carries no conditions column, per the skill).

**(c) All 64 declared constants appear with numeric values in prose.** Verified by value-probe grep across every `domain_constants` group: clock/calendar (default clock `2026-05-01T00:00:00.000Z`, both school-year date pairs and end instants), consent (14 years inclusive, both self-consentable categories, all 5 categories), enrollment cap 2, immunization (3/2 required doses, 0/365 min-age days, 28/56/28 intervals, 4-day grace, 30-day provisional window), all 6 screening bands with their inclusive/exclusive direction, clearance (365/180 days, 30-day deferral window, cap 2), referral cap 3, notification (cap 3, 14-day ack window), telehealth (15-min buffer, 15–60 duration, cap 2 reschedules, capacity default 1 / min 1 / max 4), no-show grace 10 min, sliding fee (1,560,000 + 550,000 cents, all four tier ceilings, all five discount fractions, 500-cent floor, 2,500-cent copay, 2 appeals), the full 6-line fee schedule plus the `IMMUNIZATION_ADMIN` no-charge category, and both precision constants (4 dp rates, 0 dp money).

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 129 required, 129 present, 0 missing
- endpoints[].request_body: 69 required, 69 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
- enum values: 0 missing; state enumeration values: 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 32 checked, 32 expressed as an explicit ordered ladder in §2.6 with exhaustive applies_to scopes, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_student_version + ERR_STALE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 78 checked across 12 machine entries, 78 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed incl. all 4 dual-variant calcs with both variants and the operative one named, 0 missing
- validations[] conditions: 32 checked, 32 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 67 checked, expressed, 0 missing
- entities[].fields[] structured content: 129 checked, defaults/initial values/computed sources reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked (4 clearance outcomes, 2 close-unfulfilled outcomes, 2 adjudicate outcomes, 2 outreach outcomes, 2 deliver outcomes, 2 session-close outcomes, 4 notification-birth branches, 5 charge-reversal origins, 2 billing-axis bubble targets), equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 967
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was byte-copied from `section-2.2-response-structure.md` and verified present verbatim. No fuzzy words and no operator/pseudocode leaks (checked `>=`, `<=`, `!=`, `==`, `+=`, `&&`, `||`, `IN {`, `NOT IN` outside fences/tables).

**(d) Deliberately left under-determined — one place.** `AggregateReport.grace_compliance_count` / `strict_compliance_count` are described as counting "the students in scope" for the report. The scaffold itself says only "in-scope students" and never defines the student-scoping predicate the way it defines the visit and referral scopes, so pinning a specific predicate in prose would have been invention rather than transcription. Both *countings* (grace vs strict, with the 4-day grace and exemption handling) are fully specified; only the population boundary is left as the scaffold left it.

Two faithfulness notes for downstream steps: (1) the scaffold's Visit `SCHEDULED → IN_PROGRESS` transition carries a `School.program_status == ACTIVE` precondition that rung 14's `applies_to` list does not include — I stated both (the transition precondition in §3.5, the five-endpoint ladder scope in §2.6) rather than silencing either; (2) the encounter nominal-fee floor gate reads the *live* `Student.payer_route`, not the charge's snapshot, and the prose says so explicitly since the surrounding sliding-fee rules use the snapshot.

### Orchestrator's independent verification
- `workspace/PRD.md`: 456 lines / 14,309 words.
- Independent scaffold-vs-PRD diff: **67/67 endpoints** matched, 0 missing; **38/38 error codes** present, 0 missing.

## Step 5: Generate unit tests — 2026-08-03T16:37:00.000Z

Test infrastructure and suite generated.

### Output
- `test_helpers/` — `types.py`, `api_client.py` (67 endpoint methods), `api_errors.py` (38 error IDs + status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (5 tiers), `__init__.py`
- `test_suite/` — `conftest.py` + 11 domain-named test files

### Counts
- **87 tests total.**
- **Queue A (difficulty): 18/18 instances**, each with exactly 2 tests (36 tests).
- **Queue B (corner): 50/51 non-stub instances**, ≥1 test each (51 tests; the self-consent validation instance carries 2 — the permitted path and the two refusal paths).
- The 5 `excluded_because` stubs are absent, and all 5 of their `difficulty_instance` cross-references were checked and resolve.

### SKIPPED instance (1)
**`Corner/errors/error_dose_sequence_and_duplicate_dose_on_immunization_record`** — fails filter condition 2 (unique derivability). Its asserted outcome is `ERR_DUPLICATE_DOSE` for re-recording HEPB dose 1 when a `VALID` dose 1 exists. But PRD §2.6 rung 22 sits above rung 23 and requires `dose_number` to equal `max(VALID dose numbers) + 1`; any request that would trip rung 23 necessarily has `dose_number <= max`, so it is already refused at rung 22. `ERR_DUPLICATE_DOSE` is **structurally unreachable** under the PRD's own ladder — the collapse pattern is *unreachable-guard-below-a-stricter-guard*. A faithful PRD-only implementer returns `ERR_DOSE_SEQUENCE`. The instance's other two claims (`ERR_DOSE_SEQUENCE` on an out-of-sequence dose, `ERR_VALIDATION` on a future `administered_date`) are derivable, but per the design-index-only contract the instance was skipped rather than weakened, so **`ERR_DOSE_SEQUENCE` and the rung-24 future-date check have no test in the suite** — a genuine coverage gap owned by the design index, not by the suite.

### Verification results
- Every test file compiles; `test_helpers` imports cleanly; pyflakes reports no undefined names and no unused imports.
- Every `Design:` tag resolves to a real non-stub instance **and** its rule_id/section segment matches the source YAML (0 structural errors). Every test carries exactly one `Design:` line.
- Every PRD citation was whitespace-normalised and grep-checked as a literal substring of `PRD.md`, with a ≥8-word minimum: **0 citation failures** (5 caught and repaired during the pass — two over-short fragments, one `TIER_C` fragment whose trailing punctuation diverged, one quote that paraphrased `` `patient_responsibility_cents` `` as prose).
- No `pytest.mark.skip` / `xfail` / `skipif` anywhere; no scaffold references leak into generated comments or docstrings.
- Timestamps compare semantically throughout via `assert_same_instant` / `assert_instant_ordering` / `assert_same_date`, never as rendered strings.
- All constants in `constants.py` are quoted from PRD prose, not the scaffold.

### Live run (note: isolation deviation)
Because Step 6 finished before Step 5, the test-generator was able to run one live pass against `workspace/implementation/`: **87/87 passed** (52.9s). First run was 87/88 — the one failure was the design/PRD contradiction above, which is why that instance is now skipped. One fixture bug found and fixed: `site_code` is unique across all school rows, so `create_school()` now mints a fresh code per call unless the caller pins one (two tests build two sites).
**Orchestrator note:** this breaks the intended one-way isolation (Step 6 could not see `test_suite/`, but Step 5 could see `implementation/`). Step 7 was explicitly briefed on the risk of assertions tuned to code rather than PRD and re-audited the highest-risk site; see its entry.

## Step 6: Generate implementation — 2026-08-03T16:37:00.000Z

Implementation complete and verified.

### Module layout (2,846 lines of Python + `start.sh`, 31 source files)
| Layer | File | Lines |
|---|---|---|
| Entry | `app.py` | 59 |
| Foundation | `config.py` 288, `clock.py` 151, `ladder.py` 194, `fields.py` 139, `helpers.py` 97, `store.py` 96, `errors.py` 56, `envelope.py` 49 | 1,070 |
| Services | `calc.py` 302, `billing.py` 161, `cascades.py` 90, `notifications.py` 47, `serialize.py` 21 | 621 |
| Routes | `telehealth.py` 282, `charges.py` 266, `visits.py` 266, `clearances.py` 197, `referrals.py` 196, `enrollments.py` 194, `immunizations.py` 190, `students.py` 186, `consents.py` 173, `reports.py` 165, `notifications.py` 120, `screenings.py` 110, `schools.py` 98, `ops.py` 75, `clinicians.py` 42, `__init__.py` 35 | 2,595 |

### Mandatory gate results
- **Endpoint diff (programmatic):** scaffold `endpoints[]` = 67, `app.url_map` (normalised `<id>`→`{id}`) = 67, **MISSING 0, EXTRA 0**.
- **`ast.parse`:** OK for all 31 source files.
- **`bash start.sh`:** boots on `$PORT`/`0.0.0.0`, answered `POST /sbhc/schools` → 201, `POST /sbhc/operations/daily-sweep` → 200 with `students_recomputed: 0` and `current_utc: 2026-05-01T00:00:00.000Z`, proving a fresh, empty, correctly-clocked store on every boot.
- **Functional exercise:** 5 scenario scripts (~200 assertions) covering every state machine, all 13 calculations, both variants of the 4 dual-variant rules, the 5-link void cascade, the 4-link telehealth-revoke cascade, OCC, conservation invariants and pagination — **0 failures**.

### Adjudication 1 — timestamp rendering
- **Server-written instants** (`created_at`, `updated_at`, `effective_at`, `activated_at`, `withdrawn_at`, `revoked_at`, `completed_at`, `sent_at`, `acknowledged_at`, `generated_at`, `api_request_timestamp`) render from the **logical clock** in exactly one form: `YYYY-MM-DDTHH:MM:SS.mmmZ` (PRD §2.4 "three fractional digits"). The host wall clock is never read (PRD §2.5).
- **Caller-supplied values** (`scheduled_start_at`, `start_at`, `end_at`, `to_iso8601`, `administered_date`, `report_received_date`, `date_of_birth`, `period_*_date`) are stored and echoed **verbatim**, byte for byte; parsed only for comparison, never re-rendered. `current_utc` returns the exact string the admin set (`2026-06-01T12:00:00Z` stays `…Z`, not `….000Z`).
- **Derived dates** render as bare `YYYY-MM-DD`; `expires_at` is the literal PRD §2.5 school-year end instant string.

### Adjudication 2 — enum error routing
The 38-code catalogue contains **no** enum-specific error. PRD §5 lists "unknown enum member" explicitly under `ERR_VALIDATION`, and ladder rung 6 covers "every enum … field is well formed". **Rule applied: every enum-membership failure in a request body → `ERR_VALIDATION` (400) at rung 6, without exception** — no enum routed to a different code, none falling through to a later rung. Query-string filter values are not enum-validated (rung 6 is scoped to bodies); an unknown filter value simply matches nothing.

### PRD/scaffold divergences resolved in PRD's favour
1. **Ladder beats narrative ordering.** SCAFFOLD state-machine `preconditions` lists conflict with §2.6 in several places (e.g. telehealth create: scaffold orders state→school→consent→window; PRD orders window 9 → school 14 → state 17 → consent 19). §2.6 is explicitly the arbiter, so the 32-rung `RUNG_ORDER` list in `ladder.py` governs everywhere.
2. **Visit start + suspended site.** §3.5 requires the site to still be `ACTIVE` on `POST /sbhc/visits/{id}/start`, but rung 14's scope list is declared exhaustive and omits that endpoint. Enforced as **rung 17.5** — after state legality, before the consent re-check, the exact order §3.5's sentence states — returning `ERR_SCHOOL_SUSPENDED` (409). It cannot mask `ERR_INVALID_STATE`.
3. **`granted_by_user_id` resolution on consent create.** Rung 5's endpoint list is exhaustive and excludes `POST /sbhc/students/{id}/consents`, so a guardian id belonging to another child is **not** a 404; it is `ERR_VALIDATION` at rung 6. The `STUDENT_SELF` grantor id is deliberately *not* cross-checked at rung 6, so it cannot mask rung 11 ownership or rung 12 self-consent.
4. **`payer_paid_amount_cents` on adjudicate.** Scaffold marks it unconditionally required; PRD §3.10 says a `DENIED` adjudication "forces payer_paid_amount_cents to 0". Required only on `PAID`; optional (defaulting to 0) on `DENIED`.
5. **Re-evaluation and immunization posture.** Rung 21's scope names the whole re-evaluate endpoint, but §3.9 says only a *non-`DEFERRED`* re-evaluation re-checks the posture. §3.9 wins.
6. **`School.version` on cascaded releases.** §2.4 says it advances on *every* telehealth booking or release, so `store.touch(school, force=True)` bypasses the per-request once-only guard every other row uses.

Storage is plain in-memory dicts in `store.py`; the persistence audit found no `sqlite`, file writes, `json.dump`, `/tmp` cache, or any seed/preload path.

## Step 7: Test and iterate — 2026-08-03T16:47:00.000Z

The task is complete on the first iteration — the 8-round sweep came back fully clean and independently verified.

**Iterations run: 1** (one full 8-round stability sweep, run as four waves of two via `workspace/sweep.sh`).

**Final sweep — per-round results (all 8 rounds):** rounds 1–8 each `87/87`, 87 rows, all `passed`. Every round exited 0. I did not trust the sweep script's own summary — I re-parsed all eight `results.${i}.json` files independently and confirmed 87 rows each, zero `failed`/`error`/`skipped` statuses, and that the **set of test names is byte-identical across all 8 rounds** (symmetric difference vs round 1 = 0 for every round). So no round silently collected a smaller suite. Zero flakiness surfaced: no test passed in one round and failed in another.

**Tests deleted: none.** No test failed in any round, so no test entered the diagnostic protocol.
**Fixes applied to `test_helpers/`: none.**
**Fixes applied to `implementation/`: none.**

### Verification of the two flagged risks
The prompt flagged that the Step-5 generator could see `implementation/`, so assertions might have been tuned to code rather than PRD. The single highest-risk spot — the one place the PRD was deliberately left under-determined (`AggregateReport.grace_compliance_count` / `strict_compliance_count`, where PRD §3.12 says only "the students in scope") — was checked: **the test suite never asserts either field.** All four tests in `test_11_reporting.py` confine themselves to rules stated verbatim in §3.12/§2.8 — the five-count visit partition summing to `total_visits`, the money buckets, the 0.5000 vs 0.6667 dual-variant closure rates, 4-dp rate precision, and the `ERR_INVALID_REPORT_PERIOD` / single-day-period boundary. The under-determined area is untested, which is the correct outcome.

Also confirmed: **no suppressed tests** (zero `pytest.mark.skip`/`xfail`/markers anywhere), and **in-memory storage only** (no `sqlite`, file `open(`, `json.dump`, `pickle`, `shelve`, `/tmp`, `redis`, or seed routine). Host load peaked ~7.2 on 8 cores during the final wave; no boot-timeout or "could not be restarted" ERRORs in any round, so no round needed an infrastructure re-run.

### Orchestrator's independent verification of the clean pass
Because a clean first sweep is indistinguishable from a false-clean, all of the following were re-checked directly:
- 8/8 `results.N.json` present and parseable; each `passed=87 total=87 failed=0`, **87 individual rows** (not just an aggregate counter), statuses `{passed: 87}`.
- Test-name set diff vs round 1 = **0** for all 8 rounds.
- `def test_` count in `test_suite/` = **87** == runner's collected count.
- `pytest.mark` occurrences across `test_suite/` + `test_helpers/` = **0**.
- Persistence/seed grep over `implementation/**.py` = only two *comment* lines that explicitly deny seeding; no real hits.
- Each `round.N.log` contains `Killed` exactly once — the runner SIGKILLing the pre-boot server as per-test isolation swaps in a fresh one for test #1, not a crash.

## Step 8: Finalize PRD — SKIPPED — 2026-08-03T16:48:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes**. `PRD.md` already determined every behavior the implementation exhibits at the sites the tests exercised, so there is no `<step_7_diff>` to patch against and no `PRD_FINALIZED.md` is produced. Step 9 runs from `PRD.md` directly and is the sole completeness pass.

## Step 9: Complete PRD — 2026-08-03T17:05:00.000Z

`PRD_COMPLETED.md` is complete and structurally intact: all 32 sections, 67 endpoint rows, 38 error codes, 32 ladder rungs preserved.

**File sizes:** `PRD.md` 456 lines / 102,028 chars → `PRD_COMPLETED.md` 466 lines / 122,479 chars (**+10 lines, +20,332 chars**, 33 diff hunks).

**Counts:** 33 edits — **30 ambiguity-pins**, **3 mismatch-revisions**. All edits are in-paragraph inserts or revisions; no new sections.

All 31 modules were walked, and the server was additionally booted on a spare port to empirically confirm wire-level facts (JSON float rendering, version counts, verbatim echoes, out-of-range pagination, off-enum filters).

### Changes
- **§2.2** — insert — ambiguity — `api_request_timestamp` comes from the **logical clock** not wall clock; `api_request_id` is `req_` + exactly 20 uppercase-alphanumerics — `envelope.py:14,20`
- **§2.2** — insert — ambiguity — unknown path / unsupported method → `ERR_RESOURCE_NOT_FOUND` 404 (not 405); absent or non-object body treated as `{}`; seven bodyless endpoints ignore any body; unknown properties ignored — `app.py:33-39`, `ladder.py:123-130`
- **§2.3** — insert — ambiguity — out-of-range `offset` returns an empty page with full `total_count` and `has_more` false, never an error — `serialize.py:18-21`, `envelope.py:38`
- **§2.3** — insert — ambiguity — `created_at` ties broken by **write order**, never by `id` (pervasive because the logical clock rarely moves) — `store.py:92,96`
- **§2.3** — insert — ambiguity — filters compared as **raw strings**; off-enum/unknown filter values yield an empty page, not 400; unrecognised query params ignored — `helpers.py:22-28`
- **§2.4** — insert — ambiguity — **one version bump per row per request**, with `School.version` the sole exception (once per booking/release); creation-request writes leave `version` 1, but a floor-adjusted charge opens at `version` 2 — `store.py:65-81`
- **§2.4** — insert — ambiguity — `updated_at` initialised equal to `created_at` — `store.py:48`
- **§2.4** — insert — ambiguity — the `Student.version` bump list is exhaustive (re-evaluate, revoke, unchanged sweep do **not** bump); every charge transition bumps the parent encounter — `billing.py:161`
- **§2.4** — insert — ambiguity — **timestamp rendering rule**: server-written → `…mmmZ`; caller-supplied → verbatim byte-for-byte; derived → bare `YYYY-MM-DD` — `clock.py:3-21`
- **§2.5** — insert — ambiguity — clock response `data` is `{current_utc}` echoing `to_iso8601` verbatim (offsets preserved); mutates nothing — `ops.py:16-24`
- **§2.6 rung 5** — insert — ambiguity — body-id resolution order on `POST /visits`; null/absent ids skipped; `source_visit_id` on referrals outside scope; dose `visit_id` not checked against the student — `visits.py:23-25`, `ladder.py:164-172`
- **§2.6 rung 6** — insert — ambiguity — fixed field order, first offender wins; explicit null == absent; site-code uniqueness, guardian-grantor mismatch and per-series `dose_number` ceiling all land here as `ERR_VALIDATION` — `fields.py:56-63`, `schools.py:20`, `consents.py:40`, `immunizations.py:45`
- **§2.6 rung 14** — insert — **mismatch** — `POST /visits/{id}/start` needs an `ACTIVE` site but sits *between* rungs 17 and 18, not in rung 14's exhaustive scope — `ladder.py:41`, `visits.py:176-178`
- **§2.7** — insert — ambiguity — non-integer/missing `expected_student_version` is `ERR_VALIDATION` at rung 6, ahead of 412 — `enrollments.py:43`
- **§2.9** — revise — **mismatch** — no path in the service carries two identifiers, so the different-parent rule is principle, not an enforced check (`belongs_to` is declared but never passed) — `ladder.py:81,159`
- **§3.1** — insert — ambiguity — duplicate `site_code` → `ERR_VALIDATION` 400; `sponsor_hospital_name` unbounded; `license_number` not unique — `schools.py:16-20`, `clinicians.py:20-23`
- **§3.2** — insert — ambiguity — `fpl_percent` is a JSON **number**, so 138.00 renders `138.0` — `students.py:99` (verified live)
- **§3.2** — insert — ambiguity — financial profile rewrites wholesale: omitted `insurance_member_id` clears a stored one; recomputes no posture, raises nothing — `students.py:88-101`
- **§3.2** — insert — ambiguity — `notification_opt_out` accepted at guardian creation — `students.py:135,148`
- **§3.2** — revise — ambiguity — selector tie-break is write order (was "`created_at` ascending") — `calc.py:244`
- **§3.2** — insert — ambiguity — confidentiality read off the event's encounter, so encounter-less events can never suppress as confidential — `notifications.py:21`
- **§3.3** — insert — ambiguity — activate/withdraw/reinstate fire the **full** compliance cascade (notification + clearance void + `CLEARANCE_VOIDED`) when the posture falls — `enrollments.py:124,158,192`
- **§3.3** — insert — ambiguity — withdraw cascade bumps each cancelled encounter's version and the site's version once per released session — `enrollments.py:153-155`
- **§3.3** — insert — ambiguity — reinstatement clears `withdrawn_at` but **leaves `withdrawal_reason`** — `enrollments.py:188`
- **§3.4** — insert — ambiguity — guardian-grantor failure is `ERR_VALIDATION` 400; `STUDENT_SELF` `granted_by_user_id` stored unvalidated — `consents.py:32-43`
- **§3.4** — insert — ambiguity — governing-consent search is category-only (not year-scoped); **newest-written** wins when several are usable — `helpers.py:41-50`
- **§3.4** — insert — ambiguity — TELEHEALTH revoke cascade bumps site + encounter versions; no revoke touches `Student.version` — `consents.py:161-171`
- **§3.5** — insert — ambiguity — `enrollment_id` = earliest-written match; `confidential_service_requested` stored and exposed; completion bumps the encounter's version exactly once — `visits.py:96-102`
- **§3.6** — insert — ambiguity — `duration_minutes` **truncates** seconds (15m30s → 15) and is the figure summed into booked minutes — `telehealth.py:25` (verified live)
- **§3.6** — insert — ambiguity — complete, and `NO_SHOW → CANCELLED`, leave both the total and the site's version untouched; `closure_reason` overwritten with null when omitted; reschedule preserves it and its cap sits below rungs 9/26/27 — `cascades.py:68-77`, `telehealth.py:212`
- **§3.7** — insert — ambiguity — predecessor = earliest-written match; provisional branch reads the earliest-written `ACTIVE` enrollment regardless of site/year; strict counting skips null strict dates; exemption PUT bumps version unconditionally; void link two chains in ascending dose order and preserves computed dates and `invalid_reason` — `calc.py:132-141,190-226`, `immunizations.py:173-184`
- **§3.8** — insert — ambiguity — auto-referral `reason` is the server-written sentence; link three voids **every** live clearance whatever the year or posture and is skipped silently when none exist; link four emits one notification per void in write order; direct-referral `source_visit_id` never resolved → notification `visit_id` null — `screenings.py:68,80`, `cascades.py:43-49`, `referrals.py:41-60`
- **§3.9** — insert — ambiguity — `school_year` falls back to the current year; `restrictions` stored on all outcomes; a `DEFERRED` re-evaluation keeps `outcome`; omitted `restrictions` preserved; re-evaluation does **not** bump `Student.version` — `clearances.py:79,92,183-196`
- **§3.10** — insert — ambiguity — floor step 1 clears and step 4 rewrites **every** charge, so a `REVERSED` charge retains its `patient_responsibility_cents`; floor re-derived only on complete/adjudicate/reverse; submit-claim is bodyless; `PAID` keeps a prior `denial_reason`, `DENIED` leaves the final null; chargeless encounter stays `NOT_APPLICABLE` — `billing.py:66-101,140`, `charges.py:127-141,261-265` (verified live)
- **§3.11** — insert — ambiguity — per-event `visit_id` provenance table; notifications born at version 1 — `notifications.py:13-47`
- **§3.11** — insert — ambiguity — acknowledging a null-`guardian_id` notification is 403 `ERR_OWNERSHIP_VIOLATION`, not 409 — `notifications.py:91-96,111`
- **§3.12** — revise — **mismatch** — `students_recomputed` counts **every** student evaluated, not those whose posture changed; sweep order pinned consents → clearances → students; `current_utc` verbatim; four-field `data` — `ops.py:32-75` (verified live)
- **§3.12** — insert — ambiguity — closure rates are JSON numbers, so 0.5000 renders `0.5` — `calc.py:299-302`
- **§3.12** — insert — ambiguity — an unscoped report's student population is **every** student on file — `reports.py:18-21`
- **§4** — insert — ambiguity — global response-projection rule: every endpoint returns the complete stored row, identical across create/read/list/action, with no embedded children; the two non-resource `data` shapes named — `serialize.py:8-11`

### Orchestrator's independent verification
- `PRD_COMPLETED.md` = 466 lines / 122,479 chars; tail confirms the §5 error table is intact through its last row (`ERR_INVALID_REPORT_PERIOD`) — no truncation.
- Re-diffed against SCAFFOLD: **67/67 endpoints** and **38/38 error codes** still present after the patch.

---

# Pipeline complete

Steps 1–9 done (Step 8 legitimately skipped). Final state: **87/87 tests passing on all 8 sweep rounds, 0 deletions, 0 fixes of any kind.**
