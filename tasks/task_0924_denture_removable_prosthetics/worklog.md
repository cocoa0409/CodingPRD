# Worklog — task_0924_denture_removable_prosthetics

Scenario (verbatim): `924. Denture & Removable-Prosthetics Clinic: exam & impression/scan, try-in milestone (wax/finish), fabrication & lab coordination, delivery & adjustment, reline/repair & warranty, insurance & payment plan, recall, remake`

Difficulty: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-04T03:59:30.000Z

Created `tasks/task_0924_denture_removable_prosthetics/workspace/`. Index 0924 = max existing (0923) + 1.

## Step 3: Copy INSTRUCTION.md — 2026-08-04T04:00:14.369Z

Copied `./INSTRUCTION.md` → `tasks/task_0924_denture_removable_prosthetics/workspace/INSTRUCTION.md` (1424 bytes). Done ahead of Step 2 (no effect on scaffold generation, which does not read it).

## Step 2: Generate scaffold — 2026-08-04T05:12:00.000Z

All three artifacts are generated, parse cleanly, and pass the skill's own linter. Files are at `/home/ubuntu/github/CodingPRD/tasks/task_0924_denture_removable_prosthetics/{SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml}` (the pre-existing `worklog.md` and `workspace/INSTRUCTION.md` were left untouched).

## Final counts per axis

| Axis | Count | Target | Notes |
|---|---|---|---|
| Entities | **16** | 15–16 | Patient, Coverage, DentalLab, ProsthesisCase, CaseArch, ImpressionRecord, TryInMilestone, LabCase, Prosthesis, PostDeliveryService, WarrantyClaim, RemakeRequest, Predetermination, Claim, PaymentPlan, Installment |
| Endpoints | **72** | 62–72 | 40 POST / 32 GET, incl. `POST /prosthetics/_clock/set_current_utc` (default clock `2026-05-01T00:00:00Z`) |
| Error codes | **36** | 30–36 | every one has ≥1 design-file trigger |
| State-machine axes | **14** across 13 entities | 11–14 | **all 14 non-linear**; Prosthesis carries two parallel axes (`warranty_status` × `recall_status`); 6 cyclic, 5 fan-out, 2 compound/bubble-up; 112 transitions |
| Calculations | **16** | 12+ | **6 dual-variant**: `lab_promised_due_at`, `predetermination_plan_payment`, `claim_secondary_cob_payment`, `warranty_and_replacement_clocks`, `post_delivery_service_charge`, `lab_remake_credit` |
| Validation ladder | **31 rungs** | 25–32 | all 31 grounded by ≥1 design instance |
| Roles | **6** | — | segregation_of_duties model; `LabTechnician`→`entity_backed:DentalLab`, `Patient`→`entity_backed:Patient`, 4 opaque |
| OCC rules | **3** | 3 | lab-case↦CaseArch, service↦Prosthesis, payment-plan↦ProsthesisCase — all CREATE-with-supersede |
| Conservation invariants | **4** | 3–4 | adjustment allowance (count), payment-plan principal (money), lab credit ledger (credit), coverage benefit (benefit pool) |
| Constants | **82** declared, all with concrete values | — | zero named-but-valueless |
| §1.8 instances | **24** (9 rules × ≥2) | ≥18 | |
| §1.9 instances | **57** (53 recipes + 4 `excluded_because` stubs) | — | |

Mandated devices all present: **global write gate at rung 5** with a 17-line explicit exclusion list (each with its one-line reason); **two mutate-then-reject rungs** (15 lab shelf-life→`EXPIRED`; 22 remake ceiling→`FINAL_DENIED`) each with its second-attempt pre-emption pinned in the scaffold (rung 10 `ERR_TERMINAL_STATE` and rung 11 `ERR_REMAKE_FINAL_DENIED`) and tested in §1.9; **exhaustive enum-routing rung 8** listing 18 fields and ending "No other field routes to this error; all other enum-membership failures route to ERR_VALIDATION"; a **depth-6 cascade** (remake approval → arch → prosthesis/lab-case → lab credit applied → plan re-struck → `PAID_OFF`).

## yaml.safe_load

| File | Result |
|---|---|
| SCAFFOLD.yaml | **OK** — 15 top-level keys |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | **OK** — single key `scaffold_difficulty_design` |
| SCAFFOLD_CORNER_DESIGN.yaml | **OK** — single key `scaffold_corner_design` |

Three parse defects were found and fixed: 27 `input:` flow lists containing `field?` tokens, 20 `grounds:` flow lists containing `validations[priority=N]`, and one `captures: { x: $.data[0].id }` — PyYAML terminates plain scalars at `?` and `[` inside flow context, so all were quoted.

`scaffold_lint.py` verdict (verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 72   §1.1 entities declared: 16
  §1.8 instances: 24   §1.9 instances: 53   Calls scanned: 1017
```
26 FKs (incl. 3 self-referential) all have a reverse-reachability GET.

## Undeclared-constant sweep

343 distinct ALL_CAPS tokens across the three files. Classification: **82 declared constants** (every threshold/window/ceiling/interval/fee/rate/band boundary carries a value; zero null), **36 declared error ids**, **116 enum members** harvested from `constraints:` / state names, **12 calculation `variants[].name`** values, and the remainder are prose emphasis words, acronyms (OCC/RBAC/COB/QC), sort directions (ASC/DESC) and templated-family prefixes (`FEE_<type>`, `FREQ_<type>_MONTHS`, `MILESTONES_<type>`, `RECALL_INTERVAL_<type>_DAYS`, `ALTERNATE_BENEFIT_MAP_<type>_TO`). Every expansion of every templated family was verified present — **0 undeclared constants**. Enum-value closure holds: the only values appearing once in SCAFFOLD.yaml are pure client-input enums (`arch_position`, `capture_method`, `reason_code`), each exercised as a payload literal in the design files.

## Reachability audit — defects found and repaired

1. **`ERR_WARRANTY_EXPIRED` was dead.** Rung 23 required `warranty_status == IN_WARRANTY`, but the clock-driven `IN_WARRANTY → WARRANTY_EXPIRED` fires on read, so any post-window adjudication was masked by rung 23. **Repair:** rung 23 re-scoped to "NOT in {WARRANTY_CONSUMED, WARRANTY_VOIDED}", with the pass-through stated explicitly on both the rung and the error.
2. **Rung 22 was practically unreachable.** The ceiling counted `remake_count` (APPROVED remakes), but approval moves the arch to `REMAKE_PENDING`, which rung 13 forbids as an approve from-state — so hitting the ceiling needed two complete re-fabrication cycles. **Repair:** added `CaseArch.remake_request_count` (rows in {PENDING_APPROVAL, APPROVED, DENIED}; FINAL_DENIED excluded so the counter can't run away) and re-pointed rung 22, the SM transition, `attempt_number`, the error condition and the endpoint side-effects at it. Preserves the seam's "remake-**attempt** ceiling" wording.
3. **`PostDeliveryService.COMPLETED` was terminal *and* the from-state of its own compensating void** — rung 10 would have pre-empted the void and made `adjustment_allowance_conservation` untestable. **Repair:** `terminal_states: [VOIDED]`, with a note that every non-void trigger from COMPLETED is refused by rung 12.
4. **`Claim.CLOSED` had the identical shape problem** (CLOSED→REVERSED is the compensator for `coverage_benefit_conservation`). **Repair:** `terminal_states: [DENIED, REVERSED]` plus an explicit note.
5. **Rung 29 was uncomputable and self-blocking** — phrased against "the prosthesis that anchor belongs to", which has no FK path from a Claim and would block a case's own delivery-minted claim. **Repair:** restated as a set predicate (PRIOR = prostheses under a *different* case of the same patient; compare clock to `max(replacement_eligible_date)`).
6. **`WarrantyClaim.claim_status = WITHDRAWN` had no producing transition.** **Repair:** removed from the enum.
7. **A duplicate-payment-plan uniqueness rung contradicted OCC rule 3** — it would have made create-with-supersede impossible and the race unreachable. **Repair:** rung and `ERR_PLAN_DEFAULTED` dropped; superseding an ACTIVE/DELINQUENT plan is legal, a DEFAULTED one is refused by rung 12.
8. **Rung 13 for `POST /lab-cases` carried an escape hatch no endpoint could exercise** ("or a post-delivery service purpose" — those lab cases are cascade-created by `POST /services`). **Repair:** tightened to `arch_status == LAB_FABRICATION`.
9. **`reason_code = RECALL_EVALUATION` had no exercising test.** **Repair:** added corner instance `recall_remake_evaluation_auto_creates_a_recall_reason_remake_request`.
10. **Prompt-pay-discount down-payment floor was genuinely two-way ambiguous** (pre- vs post-discount base), which would have made the pinned literal in `prompt_pay_discount_tier_keyed_on_pre_discount_subtotal` unverifiable. **Repair:** rung 7 and the payment-plan endpoint both pin the floor to the **pre-discount** `patient_responsibility_amount`.

Also swept: no forbidden concurrency vocabulary anywhere (one "runs in parallel with the sibling arch" was reworded); all 4 `excluded_because` stubs cite existing §1.8 instance names and carry no `test_recipe`; instance names are unique across both design files. All formula-derived assertions were computed in Python and written as literals (e.g. installment residual `137.16` on row 7 of `960.00/7`; prompt-pay `2500.00 → 125.00 → 2375.00` with the re-tiering trap; COB `600.00` STANDARD vs `120.00` NON_DUPLICATION; the two clocks `2027-09-01` warranty vs unchanged `2031-05-01` replacement).

**Orchestrator independent verification:** all 3 files `yaml.safe_load` OK; SCAFFOLD.yaml has 15 top-level keys with neither `scaffold_difficulty_design` nor `scaffold_corner_design`; entities 16; endpoints 72; §1.8 instances 24; §1.9 instances 57. Sizes: SCAFFOLD 213 KB, CORNER 195 KB, DIFFICULTY 143 KB.

## Step 4: Generate PRD — 2026-08-04T05:33:00.000Z

## Output
`workspace/PRD.md` — **714 lines, 18,472 words**, written in 11 bounded Write/Edit appends.

## Section structure
- **§1 Introduction** (3 paragraphs: parallel clinical/fiscal calendars, the three structural commitments)
- **§2 Global Specifications** — 13 subsections: 2.1 RBAC & identity · 2.2 Response structure (verbatim) · 2.3 Pagination & ordering · 2.4 Identity/versioning/response projection · 2.5 Timestamps · 2.6 Logical clock · 2.7 Money & rounding · 2.8 OCC · 2.9 Path resolution · **2.10 The 31-rung ladder in full** · **2.11 The global write gate** · **2.12 Mutate-then-reject** · 2.13 Cascades & conserved quantities
- **§3 Business Logic** — 9 subsections: registration · case intake/arch/exam · impressions · try-ins · lab coordination · delivery/warranty/recall · services/warranty fault/remake · insurance · case balance & collections
- **§4** 72-row endpoint table (4 columns) · **§5** 36-row error table (2 columns)

## Per-axis coverage (rendered vs declared)
| Axis | Declared | Rendered |
|---|---|---|
| Entities | 16 | 16 |
| Entity field names | 149 | 149 (exact backtick match) |
| Endpoint input/query identifiers | 81 | 81 |
| Path parameters | 16 | 16 |
| Endpoints | 72 | 72 (method/path/roles verified programmatically — zero drift) |
| State-machine axes | 14 | 14 |
| Transitions | 112 | 112 (sibling legs rendered as collective rules naming every origin state exhaustively) |
| State enum values | 65 | 65 |
| Calculations | 16 | 16 (all 6 dual-variant ones with both variants) |
| Ladder rungs | 31 | 31, in order, each with error id + HTTP status + scope |
| Error codes | 36 | 36 (statuses verified against scaffold — zero drift) |
| Constants | 82 | 82, each rendered **at its point of use** in prose (no constants table) |
| OCC rules | 3 | 3 |
| Conservation invariants | 4 | 4 (forward + compensating action each) |
| Roles | 6 | 6 |

Specifically requested items: rung 8's **18-field enum list reproduced in full with the closing "no other field routes to this error" sentence**; both mutate-then-reject rungs rendered with their *second-attempt* pre-emption (rung 15 → `ERR_TERMINAL_STATE` via rung 10; rung 22 → `ERR_REMAKE_FINAL_DENIED` via rung 11, with "no second `FINAL_DENIED` row is minted"); the write gate rendered as a 12-endpoint gated family **plus** the full outside-the-gate list with the reason for each; one global timestamp rule covering server stamps, echoed caller instants, derived instants, and the explicit statement that deadlines are instants preserving time-of-day, never end-of-day.

## Scaffold contradictions found (rendered explicitly, NOT adjudicated — carried forward as friction points)
1. **Recall overdue boundary.** Calculation `recall_schedule` bands `OVERDUE` at `now >= recall_due_at + 30d` ("inclusive"); state-machine axis 7 requires "strictly after". Rendered as a named friction note in §3.6 stating both readings; only the single boundary instant is disputed; no behaviour pinned.
2. **Coverage rank uniqueness claimed by two rungs.** Rung 7 lists `(patient_id, rank)` among its uniqueness checks (`ERR_VALIDATION`/400); rung 27 restates it as `ERR_COB_RANK_CONFLICT`/409. Strict ladder order makes rung 27 dead. Rendered as a friction note at the end of §2.10.
3. **`LAB_FAULT` without `attributed_lab_case_id`.** Transition precondition requires it non-null; the `lab_remake_credit` `CLINIC_BORNE` variant contemplates "LAB_FAULT with no attributed lab case" → 0.00 credit. Friction note in §3.7 carrying both.

## Under-specifications resolved (and how)
- **Emergency-repair carve-out scope**: rung 5's gated-family line says "when `is_emergency_repair` is false" while the endpoint and field descriptions require `REPAIR` **and** the flag. Rendered as the conjunction (2-of-3 agreement), stated explicitly in §2.11.
- **`complete-exam` with no arches** → `ERR_VALIDATION` (rung 7).
- **`amount_paid` ≠ installment `amount`** → `ERR_VALIDATION` (rung 7), alongside the declared `> 0` range.
- **Resend past `shelf_life_expires_at`** → `ERR_LAB_CASE_EXPIRED`/409 *without* an accompanying write; mutate-then-reject confined to the receive path.
- **`ALTERNATE_BENEFIT` when `alternate_benefit_enabled` is false or no downgrade target exists** → `ERR_VALIDATION`.
- **`WARRANTY_NO_CHARGE` service branch** — no endpoint auto-creates a service from a claim; rendered via the only observable link, a claim citing the service through `post_delivery_service_id`.
- **Rung 23 vs adjudicate preconditions**: rendered per rung 23 (which explains itself) — `WARRANTY_EXPIRED` passes so rung 24 stays reachable.
- **`NO_ACTION` recall from `RECALL_SCHEDULED`**: rendered explicitly as "has no declared destination".
- **Rung 3's ownership map** names `ProsthesisCase.patient_id` but `applies_to` omits the case read → map includes the mapping, enforcement on exactly the five listed endpoints.
- Minor addition (not in scaffold): list ordering tie-break by `id` ascending, for pagination stability.
- Scaffold self-count nit: calculations header comment says "15 calculations"; the list contains **16**. All 16 rendered.

## Hard contract reports
```
Field coverage: entities 149/149, endpoint inputs 81/81, path params 16/16, state enums 65/65, errors 36/36, roles 6/6 — PASS
Rule coverage: rungs 31/31, OCC 3/3, transitions 112/112, calculations 16/16, side_effects 72/72, fields 149/149, invariants 4/4, constants 82/82, sibling-branch symmetry 11/11 groups — PASS
Path purity (§3): 1235 backtick tokens scanned, 0 paths / 0 bare methods / 0 method+path — PASS
```
Nothing in the scaffold was left unrendered.

## Step 5: Generate unit tests — 2026-08-04T06:05:00.000Z

**Queue A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (24 instances): 24 emitted, 0 skipped, 48 tests (exactly 2 per instance).**
All 24 passed the PRD-first filter. One fixture deviation worth flagging: `dual_variant_calc/warranty_clock_restarts_while_replacement_clock_does_not` is built on an `IMMEDIATE_DENTURE` (empty `required_milestones`) rather than the yaml's `FLEXIBLE_PARTIAL`. The asserted clock values are type-independent, but the yaml's path re-books a `WAX` try-in after a remake restart, and there the PRD is genuinely two-readered (§3.3 "next_required_milestone set to the first entry of that list" vs §3.2's "first entry … not yet present in completed_milestones"). Routing through a type with no milestones keeps the asserted outcome uniquely derivable.

**Queue B — `SCAFFOLD_CORNER_DESIGN.yaml` (57 instances): 53 emitted (1 test each), 4 not translated because they are `excluded_because` stubs — all four cross-references resolve to real difficulty instances.**
No corner instance failed the filter outright. Two assertion-level relaxations:
- `Corner/validations/duplicate_primary_coverage_rank_is_rejected` — friction point #2. PRD §2.10 states both readings and explicitly declines to resolve, so the test uses `validate_error_is_one_of([ERR_COB_RANK_CONFLICT, ERR_VALIDATION])` (the permitted relaxation) and still pins that no second coverage survives.
- `Corner/cross_cutting_layers/payment_plan_supersede_waives_the_previous_schedule` — the yaml asserts waived rows carry `amount 0.00`, but PRD §3.9's supersede leg only moves the status to `WAIVED`; zeroing the amount is stated only for the lab-credit re-strike. The `amount 0.00` assertion was dropped; status/`superseded_by_plan_id`/new-schedule assertions are all kept.

**Friction points:** #1 (recall `OVERDUE` boundary) and #3 (`LAB_FAULT` with no `attributed_lab_case_id`) forced no skips — no instance asserts on the disputed side. Every recall-overdue assertion sits at `2026-08-30`, strictly after `recall_due_at + 30 days`, which both readings agree on.

**Output:** **101 tests** (48 difficulty + 53 corner), 0 skipped/xfail/skipif markers. `test_helpers/`: `__init__.py`, `types.py`, `api_client.py` (77 endpoint methods), `api_errors.py` (36 codes), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (~640 lines, 5 tiers). `test_suite/`: `conftest.py` + 12 domain-named files.

**Verification performed:** all 101 tests carry exactly one `Design:` line resolving to a real instance (0 bad/untagged/dual-tagged); 24/24 difficulty instances ≥2 tests, 53/53 non-stub corner instances ≥1 test; 216 quoted PRD spans checked against PRD.md — 0 verbatim failures; `parse_instant`/`assert_same_instant` used for all 32 instant-valued fields — **0 raw-string equality comparisons**; `workspace/implementation/` never read; suite collects cleanly (101 collected).

## Step 6: Generate implementation — 2026-08-04T06:44:00.000Z

**Isolation note (orchestrator):** Steps 5 and 6 were NOT launched concurrently — an orchestrator error sent only Step 5. To restore the physical isolation the pipeline depends on, `test_suite/` and `test_helpers/` were **moved out of the task tree entirely** (to a scratchpad dir) for the whole duration of Step 6, and moved back only after it exited. Step 6 therefore ran against an even stricter isolation than the normal concurrent launch provides — the test directories did not exist on any path under `tasks/` while it ran.

**File layout (4,793 lines):** `start.sh` 13 · `requirements.txt` 1 · `app.py` 94 · `pconst.py` 330 (all 82 constants) · `util.py` 199 (the single instant renderer) · `errors.py` 88 · `store.py` 112 · `envelope.py` 46 · `guards.py` 400 (rungs 1–10, 12, pagination, filters) · `nav.py` 168 · `calc.py` 158 (the 16 calculations) · `domain.py` 384 · `projections.py` 340 · `routes/` (11 files) 2,460.

**url_map completeness diff:** declared = 72 · registered = 72 · **MISSING = 0 · EXTRA = 0** (re-run as the last action after the final edit).

**Timestamp rendering:** one rule, `util.iso()`, used by every field — **`YYYY-MM-DDTHH:MM:SS.sssZ`**, exactly three fractional digits, trailing `Z`. All four categories go through it because every instant is stored as an aware UTC `datetime`, never as a string: server-written stamps `iso(now())`; caller-supplied instants parsed on the way in (so `2026-05-01T00:00:00Z` reads back `...T00:00:00.000Z`); derived instants same renderer with time-of-day preserved and no midnight snapping; clock echo same renderer. `date_of_birth` is the one deliberate non-instant: plain `YYYY-MM-DD`, echoed verbatim.

**Enum routing:** strict iff. `guards.INVALID_ENUM_FIELDS` is a frozen set of exactly the 18 fields PRD rung 8 enumerates and `check_enum()` asserts membership in it — the only path to `ERR_INVALID_ENUM`/422. Every other enum-membership failure (list filters, server-computed enums, missing enum fields) routes to `ERR_VALIDATION`/400 at rung 7. Verified: bad `prosthesis_type` → 422; bad `case_status` filter → 400; missing `prosthesis_type` → 400.

**Friction-point choices (impl-gen's adjudication):**
1. **Recall `OVERDUE` boundary → INCLUSIVE** (`clock >= overdue_at`), matching the `recall_schedule` banding formula and its `precision` note.
2. **Coverage `(patient_id, rank)` uniqueness → rung 27, `ERR_COB_RANK_CONFLICT`/409** — chosen so the dedicated code stays reachable, and because PRD §3.1 states it in prose. `(case_id, arch_position)` stays at rung 7/`ERR_VALIDATION`.
3. **`LAB_FAULT` with no `attributed_lab_case_id` → REFUSED** with `ERR_VALIDATION`/400 at rung 7, on both `/adjudicate` and `/clinical-review`. The 0.00 `CLINIC_BORNE` branch is therefore unreachable for LAB_FAULT.

**Per-axis confirmation:** 16 entities · 72 endpoints · 14 SM axes (incl. `Prosthesis` warranty × recall as independent parallel axes on one row) · every declared transition incl. all cyclic legs · 16 calculations (6 dual-variant) · 31-rung ladder · 36 error codes · 3 OCC rules · 4 conservation invariants, all exercised through both forward and compensating actions. Both mutate-then-reject rungs commit then raise, and the second attempt reports the pre-empting rung's code (`ERR_TERMINAL_STATE`, `ERR_REMAKE_FINAL_DENIED`) with no second `FINAL_DENIED` row minted.

**Storage:** pure in-memory dicts, empty on every boot; grep confirms no `open()`, sqlite, pickle, JSON dump, `/tmp` cache, or `seed_*`. Cold boot served its first request in **242 ms**.

**Two implementation notes flagged by impl-gen:**
- **Ids are monotonic-prefixed v4 UUIDs.** Rows minted in one cascade share `created_at` and the declared tie-break is `id` ascending; a random UUID made list order arbitrary. The first 48 bits are now a counter (version/variant nibbles untouched), so the declared tie-break yields creation order.
- **One real dead-end fixed.** After a remake, an arch re-entering `MILESTONE_PENDING` has every required milestone already in `completed_milestones`, so `next_required_milestone` is null and no try-in can ever be booked — the remake loop was unreachable for milestone-bearing types. The declared `MILESTONE_PENDING → LAB_FABRICATION` transition now fires as soon as its stated precondition (`next_required_milestone is null`) holds. First-round behaviour is byte-identical; the empty-list branch still holds only for `IMMEDIATE_DENTURE`.

**Orchestrator independent verification:** own url_map-vs-scaffold diff → 72 declared / 72 registered / **0 MISSING / 0 EXTRA**; `grep -rIl "test_suite|test_helpers|conftest" implementation/` → **empty** (no test references anywhere in the impl tree); persistence grep → only a `json.dumps` for HTTP response serialization and a comment in `store.py`; `def test_` = 101 == `Design:` tags = 101; skip/xfail/skipif markers = 0.

## Step 7: Run tests and iterate — 2026-08-04T07:05:00.000Z

Task complete — **clean first-sweep pass, zero changes required.**

**Iterations run:** 1. The first 8-round sweep came back fully green, so the diagnostic protocol had an empty failure union and no fix/rerun cycle was needed.

**Final sweep (all 8 rounds):** `101/101` each — rounds 1–8, `failed=0 errors=0 skipped=0`. Verified genuine, not a harness artifact: each `results.N.json` holds 101 test records, all 8 rounds ran the **identical** 101-name test set, durations 59.6–60.5s. Each `round.N.log` contains exactly one `Killed` (the expected per-test isolation swap on test #1); no EADDRINUSE, no "could not be restarted", no SIGTERM/143. No `skip`/`xfail`/`pytest.mark` anywhere in the suite.

**Tests deleted:** none. No test failed, and no test was found to violate STEP 1a coverage or STEP 1b unique derivability.
**Fixes applied to `test_helpers/`:** none. **Fixes to `test_suite/`:** none. **Fixes to `implementation/`:** none. A `find -newermt` over the task tree confirms no source file was touched.

### Isolation-overlap audit (mandatory — Step 5 finished before Step 6 began)

All five mandated categories, plus two extra checks. Four of five came back **empty**.

1. **Raw timestamp string equalities — EMPTY.** Zero literal-instant string comparisons, zero `==` on any `_at`/`_date`/`_on` field, zero `isoformat`/`strftime`/`.replace(...Z)` routes. All 21 distinct instant fields touched by tests go through `assert_same_instant` (53 call sites), which parses both sides and compares semantically. Step 5's claim verified.
2. **List-ordering / unstated tie-break — EMPTY.** 15 index sites; every one is either preceded by a singleton guard (`assert len(...) == 1` / `meta["total_count"] == 1`) or taken from a list the *client* re-sorts (`sorted_by_sequence`; `fx.installments_of` sorts by `sequence_number` before returning). No test relies on server-side ordering.
3. **`version` pinned to a number — EMPTY (one benign literal).** Only `assert patient["version"] == 1`, backed verbatim by PRD:111 *"an integer that starts at 1 when the row is created"*. Every other version assertion is relative (`== before["version"]`, `== current_version + 1`).
4. **Response fields PRD never names — EMPTY.** All 146 asserted field names checked against PRD; the 10 misses are local ctx/fixture dict keys, not response fields. The computed-field-silence candidates were probed individually and all are real declared attributes — §3.9 deliberately backticks its four named case fields and leaves the five intermediates as un-named bold prose; the tests only assert the backticked ones.
5. **Cascade leg where PRD renders only the happy path — EMPTY, with one watch item.** 117 downstream/cascade assertion sites examined, 0 suspect. The two mutate-then-reject assertions — the shape that usually breaks — are each backed by a verbatim *"That write is committed"* sentence (PRD:295 rung 15, PRD:299 rung 22). The many "error branch wrote nothing" assertions rest on PRD:183, which names §2.12 as the only exceptions.

**Watch item (reported, not actioned):** `test_12:117` and `test_12:260` assert a successful `POST /lab-cases` bumps the parent arch's `version` when there is **no** prior `DRAFT` to supersede (line 250 asserts zero lab cases exist first). PRD:389 states that bump as a coordinate clause *inside* the supersede elaboration, so it could be misread as supersede-only. It survives unique-derivability because PRD:158 says the OCC guard exists so *"a second create working from a stale view of the arch would silently discard the first dispatch plan"* — without a bump on the first, non-superseding create, the guard is inert in exactly the scenario PRD says it protects. **Step 9 should promote that bump to a standalone sentence** (as the parallel payment-plan rule at PRD:579 already does).

**Two extra checks worth flagging:**
- **The three known friction points are handled correctly, which is strong counter-evidence to leakage.** Friction 2 is already relaxed to `validate_error_is_one_of([ERR_COB_RANK_CONFLICT, ERR_VALIDATION])` with the PRD friction note quoted in the docstring; friction 3 (`LAB_FAULT` without `attributed_lab_case_id`) is untested; friction 1's disputed instant is *sidestepped* — the `IMMEDIATE_DENTURE` recall lands at `2026-07-30`, +30d = `2026-08-29`, and the tests probe `2026-08-01` (DUE) and `2026-08-30` (OVERDUE on **both** readings), never `2026-08-29`. A suite written against the implementation would have pinned all three.
- **`implementation/` carries two SCAFFOLD docstring references** (`calc.py:1`, `pconst.py:4` — *"Values are taken verbatim from SCAFFOLD.yaml constants"*), the known-benign impl-gen-peeks-design-YAML pattern. Verified harmless: all 72 numeric constants in `pconst.py` have their value present in PRD.md, so nothing unrecoverable-from-PRD leaked in.

Assertion strength was preserved throughout: all 53 `validate_error` sites carry an explicit `ApiErrorId`, the single `validate_error_is_one_of` relaxation being the PRD-sanctioned one.

**Orchestrator independent verification of the clean pass** (per the clean-first-sweep protocol — a false-clean looks identical to a real one): all 8 `results.N.json` re-parsed from disk → **101 individual test rows each** (not just an aggregate counter), status distribution `{'passed': 101}` in every round, sorted test-name lists **byte-identical to round 1 in all 7 comparisons**; `pytest.mark` occurrences across `test_suite/` + `test_helpers/` = **0**; `find -newer results.8.json` over the impl and test trees = **empty**, so the 101/101 × 8 result describes exactly the shipped code.

## Step 8: Finalize PRD — SKIPPED — 2026-08-04T07:06:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes**. There is no `<step_7_diff>` to patch against, so `PRD.md` already determined every behaviour the implementation exhibits at every site the suite exercised. `PRD_FINALIZED.md` is intentionally absent; Step 9 starts from `PRD.md` and carries the entire completeness burden.

## Step 9: Complete PRD — 2026-08-04T07:28:00.000Z

**Files**: `workspace/PRD.md` (714 lines, 132,919 chars) → `workspace/PRD_COMPLETED.md` (730 lines, 175,111 chars); **+16 lines, +42,192 chars**. 83 source lines revised in place, 2 lines purely inserted; 30 headings and 112 table rows unchanged (no new sections, no table restructuring).

**Counts**: **57 edits — 39 ambiguity-pins, 18 mismatch-revisions.**

### The ten richest veins — what each returned

1. **Version-bump granularity** — richest by far, **21 findings**. Nine "writes without bumping" (arch on receive, arch on exam-close reprice, prosthesis on service complete/void, patient on delivery, lab ledger ×2, coverage ×2, plan on payment, plan on reverse-payment, case on every money recompute), plus the arch's *unconditional* bump on lab-case create (Step-7 carry-over confirmed), the plan's *unconditional* bump on every sweep, the created-at-1 rule, and the per-request cap overriding §3's per-transition prose (two-axis prosthesis moves, chained recall banding).
2. **Gate-scope asymmetry between siblings** — **9 findings**. Remake leg of start-fabrication skips rung 30 and the milestone recompute; second-stage claim submit runs 1 of 4 rungs; resend re-runs neither dispatch overlap rung; deny runs neither of approve's rung-13 checks; system-minted lab case vs caller-drafted one (no supersede, no arch bump, no rung 13); system-minted remake requests bypass rungs 11/22; auto-minted hard reline skips OCC/supersede/rungs 25-26; `GET /patients/{id}` ownership vs the other four; chairside `dental_lab_id` still FK-checked.
3. **No-op / non-clearing branches** — **8 findings**. Void leaves `charge_basis` and `completed_at`; claim reversal leaves `patient_responsibility_amount` and `adjudicated_at`; remake link 3 leaves `last_lab_received_at`; reverse-payment leaves `plan_status`; cancellation leaves the balance and `fee_schedule_total`; resend leaves `shelf_life_expires_at`/`dispatched_at`/`promised_due_at`; `retake_required` silently flips false on supersede; three free-text reason fields (`cancellation_reason`, `denial_reason`, `reversal_reason`) validated then discarded.
4. **Response-field projections** — **mostly negative, and worth recording**: one projection function per entity, used identically for create, detail and list row; nulls always emitted; collection fields always arrays. The only real finding was the set of **derived** fields (11 of them), which changes what a bump means rather than what a body contains. Pinned as a single §2.4 paragraph.
5. **List ordering and tie-breaks** — **3 findings**. The `id` tie-break is *mint order* (monotonic-prefixed UUIDs); off-enum filter → 400 vs unknown-id filter → empty page; undeclared params ignored, empty-string params = omitted. Sort key/direction were already pinned correctly.
6. **Timestamp rendering** — **1 large finding, 1 negative**. `api_request_timestamp` comes from the **logical clock** (repeats verbatim within one instant) — the single highest-impact silence in §2. Otherwise the four instant categories all go through one renderer with no exceptions, exactly as §2.5 claimed; the only additions were the *input* rules (bare dates rejected, offsets converted).
7. **404 vs 403 vs 400 routing order** — **4 findings**. The ownership/404 split across the five rung-3 endpoints (the standout: `GET /patients/{id}` is the only one that answers 403 for a non-existent row, because its owner is the path value itself); rung 7's amount/arch-count checks sitting above the state rungs; the alternate-benefit 400 sitting *below* them; the 405 case.
8. **Cascade legs that do NOT fire** — **6 findings**. Remake links 4/5/6 skipped whole when no credit moves; link 3's appliance half skipped with no prior delivery; delivery link 4 skipped with no primary coverage and link 3 skipped while siblings are unsettled (both already pinned); `INDETERMINATE` skipping the balance re-run; case closure not evaluated at five of the places that could satisfy it.
9. **"Does any endpoint actually consult this field?"** — **6 findings, all mismatches**. `Coverage.replacement_frequency_months` is **completely dead**. The §3.4 arch-state preconditions on try-in approve *and* reject do not exist. "One claim per case" is unenforced, as is the claim's coverage rank. `patient_id`/`case_id` on a plan are never cross-checked. `superseded_prosthesis_id` is scoped by nothing.
10. **Summary/table lines drifting from §3 detail** — **6 findings**. The §4 preamble's 201 rule (three minting endpoints answer 200); rung 13's "exactly seven"; rung 7's uniqueness-pair list; rung 31's "runs 28, 29, 30, 31"; §3.9's seven-item trigger list (actually nine); the complete-exam table row's "every arch". The §5 error table itself was **clean** — all 36 rows match `errors.py:12-49` exactly, and the §4 role column was clean across all 72 rows.

### Three friction points — all resolved against the code

1. Recall `OVERDUE` boundary → **inclusive** at `recall_due_at + 30 days` (`domain.py:131`).
2. Coverage `(patient_id, rank)` uniqueness → **rung 27 / `ERR_COB_RANK_CONFLICT` / 409** (`registry.py:99-101`), with `(case_id, arch_position)` confirmed still at rung 7 / `ERR_VALIDATION` / 400 (`cases.py:154-158`).
3. `LAB_FAULT` with no `attributed_lab_case_id` → **refused**, `ERR_VALIDATION`/400 at rung 7, on **both** paths (`warranty.py:140-143`, shared by adjudicate and clinical-review); the 0.00 `CLINIC_BORNE` credit branch is unreachable.

The neutral both-readings friction notes were replaced with the single pinned behaviour in each case.

### Step-7 carry-over and the two flagged impl choices — all pinned

- §3.5 — the parent arch's `version` bumps on **every** successful lab-case create, promoted to a standalone sentence matching the §3.9 payment-plan shape (`labwork.py:57-61`).
- §2.3 — ids are minted monotonic so the `id`-ascending tie-break equals **creation order** (`util.py:43-61`).
- §3.3 — `MILESTONE_PENDING → LAB_FABRICATION` fires as soon as `next_required_milestone` is null; on a remake restart the arch skips through to `LAB_FABRICATION` in one call, one `version` bump (`clinical.py:109-124`).

**Orchestrator independent verification:** `PRD_COMPLETED.md` heading structure is **byte-identical** to `PRD.md` (no new sections, as required); `find -newer results.8.json` over `implementation/`, `test_suite/`, `test_helpers/` = **empty**, so Step 9 changed documentation only and the 101/101 × 8 result still describes the shipped code.

---

# Pipeline complete

| Step | Status |
|---|---|
| 1 Task directory | done |
| 2 Scaffold | done — 16 entities / 72 endpoints / 14 SM axes (all non-linear) / 16 calcs / 31 rungs / 36 errors / 82 constants; 10 reachability defects self-repaired |
| 3 INSTRUCTION.md | done |
| 4 PRD | done — 714 lines / 18,472 words; 100% scaffold coverage; 3 frictions rendered un-adjudicated |
| 5 Unit tests | done — 101 tests (48 queue-A + 53 queue-B), 0 instances skipped |
| 6 Implementation | done — 4,793 lines / 24 files; 72/72 routes, 0 missing, 0 extra |
| 7 Test + iterate | **clean first sweep — 101/101 × 8 rounds, 0 deletions, 0 fixes** |
| 8 PRD finalize | skipped (skip condition met) |
| 9 PRD complete | done — 57 edits (39 pins + 18 mismatches) → `PRD_COMPLETED.md` |
