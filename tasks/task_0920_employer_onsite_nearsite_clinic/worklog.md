# Worklog — task_0920_employer_onsite_nearsite_clinic

Scenario (verbatim from user):

> 920. Employer On-Site & Near-Site Clinic: eligible-population & enrollment, visit (primary/occ-health/wellness), biometric & health-risk assessment, referral & navigation, vendor/staffing & hours, utilization & ROI reporting, confidentiality wall, incentive integration

Difficulty: **beyond-Expert** (user request: "generate task hard than expert level!").

## Step 1: Create task directory — 2026-08-03T17:27:30.000Z

Created `tasks/task_0920_employer_onsite_nearsite_clinic/` and `tasks/task_0920_employer_onsite_nearsite_clinic/workspace/`. Index 0920 = highest existing (0919) + 1.

## Step 3: Copy shared files — 2026-08-03T17:27:32.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0920_employer_onsite_nearsite_clinic/workspace/INSTRUCTION.md`. (Run ahead of Step 2 since it has no dependency on the scaffold.)

Also pre-staged `workspace/sweep.sh` (orchestrator-authored 8-round sweep as 2 waves of 4, with a `SWEEP_DONE` marker and an explicit no-`pkill` comment) so Step 7 does not have to author it.

## Step 2: Generate scaffold — 2026-08-03T18:20:00.000Z

All three files are written, parse cleanly, and the skill's lint returns a clean verdict.

## Final counts

| Dimension | Value |
|---|---|
| Entities | **14** (Employer, Site, VendorContract, Provider, StaffingShift, EligibilityRecord, Participant, Appointment, Visit, HealthAssessment, Referral, AlternativeStandard, IncentiveAward, ReportingPeriod) |
| Endpoints | **70** (flat collections at root; `api_prefix: "/"`) |
| State machines | **10**, of which **10 non-linear** — 2 parallel-axis pairs (Participant enrollment×authorization, Visit encounter×disclosure), 4 cyclic, 3 capped self-loops, 2 multi-way terminal fan-outs |
| Calculations | **13**, of which **7 dual-variant** (HRA scoring, incentive amount, program cap, vendor fee model, engagement denominators, referral SLA, disclosure projection) across 7 different entity domains |
| Combinatorial modes | (a) HRA 5-input band selection, (b) ROI round-per-category-then-sum, (c) true-up evaluation order — all three modes |
| Error codes | **35** |
| Validation rungs | **25**, one global ordered engine; rung 3 (confidentiality wall) pre-empts existence/payload, rung 6 (period freeze) pre-empts payload/OCC/state |
| OCC rules | **3** (Site on booking, Participant on award create, Visit on amend) |
| Conservation invariants | **3** (incentive money, site slot partition, employer quota partition) |
| Max cascade depth | **5** (RAS complete → assessment → retroactive award → period buckets → employer budget); two more at depth 4 |
| Roles | **7**, `segregation_of_duties` model |
| §1.8 | 9 rule_ids / **23 instances** |
| §1.9 | 9 sections / **44 instances** (3 `excluded_because` stubs) |

## Verification results

- **YAML**: `yaml.safe_load` OK on all three files. Hit the known `?`-in-flow-sequence offender on `input: [..., field?]` lines and fixed it by quoting every optional-input token.
- **Constants**: **49 declared with concrete values** (47 numeric/date + 2 role sets). Grep for `*_WINDOW_DAYS`, `*_BUFFER_MINUTES`, `*_THRESHOLD`, `MAX_*`, `MIN_*`, `*_CAP`, `*_RATE`, `*_PCT*`, `*_CENTS` and every ALL_CAPS token → **zero undeclared**.
- **Lint**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (835 calls scanned, clean on first run.)
- **Forbidden vocabulary**: two incidental hits ("at the same time of day", "simultaneously withdraws") rephrased; now zero.
- **Grounds**: all 200+ `grounds:` refs machine-resolved against §1.1–§1.7 → 0 unresolved.

## Reachability defects found and fixed

1. **`ERR_SEGREGATION_OF_DUTIES` was unreachable.** As first drafted, SoD compared the authorizing `CareNavigator` against `Visit.provider_id` — but visit providers are always `provider_function: CLINICIAN` and navigators always `NAVIGATOR`, so the two ids could never be equal. Fixed by re-scoping SoD to `authorizer ≠ Referral.raised_by_provider_id`, adding the `raised_by_provider_id` FK (set at creation, copied unchanged through a redirect so the constraint survives the cycle), plus the matching filter on `GET /referrals`, rung-22 text, error condition and role description.
2. **Dead enum value.** `HealthAssessment.outcome_credit_status` described a `NOT_APPLICABLE` value no path writes — removed.
3. **Unexercised terminal state.** `Referral.CLOSED_LOOP` and `POST /referrals/{id}/close-loop` had no test; extended the SLA-escalation corner instance with a loop closure that also proves `escalated_at` is preserved. Similarly added explicit asserts for `IncentiveAward.APPROVED`, `Participant.NOT_REQUESTED`, and a `NAVIGATION` staffing shift. Every declared state and enum value is now produced and named by at least one instance; every one of the 35 error codes is referenced by a design instance.

## Seams used vs dropped

Used: the **confidentiality wall as a global access-gate rung** (rung 3, pre-empting 404 so the wall cannot leak existence) with the OCC-health/wellness disclosure asymmetry as a dual-variant projection; **small-cell suppression** (MIN_CELL_SIZE 6, role-dependent, zero-cells exempt); **eligibility/enrollment lifecycle** with closed coverage spans, retro-termination and a cyclic ACTIVE↔TERMINATED machine with a 30-day grace and a CLOSED terminal; **three visit tracks on parallel axes** (encounter × disclosure, forking payer, disclosability and entitlement); **dual-variant biometric/HRA scoring** (measured vs attested, 1.25 unverified multiplier, missing-metric points); the **RAS path with retroactive credit** as the depth-5 cascade; **incentive cap + money conservation** with a tobacco tier; **referral steerage, SLA tiers and the DECLINED→REDIRECTED cycle** with chain-head-only counting; **staffing, credential expiry, slot capacity and cross-employer near-site quota** (second conservation invariant, plus `quota_contract_id` pinned so "whose quota" is observable); **three distinct report denominators + ROI whose value depends on rounding order**; the **period-finalization freeze as a second write-gate** producing a LOCKED visit state and a capped restatement cycle; the **fee-model fork with minimum-guarantee true-up**; **deliberately opposite interval conventions** (eligibility closed / provider occupation half-open / staffing containment closed, all stated inclusively in words); and **prospective-only authorization revocation** as an explicit non-firing cascade leg. Dropped: nothing substantive from the seam list, though the near-site "shared by multiple employers" idea was kept as quota-per-contract rather than a separate allocation entity, and payroll batching was folded into per-award export/mark-paid (PayrollProcessor) instead of a 15th entity — depth over breadth.

**Orchestrator independent verification of Step 2 (see below, after Step 4 entry).**

## Step 4: Generate PRD — 2026-08-03T18:36:00.000Z

PRD generated at `workspace/PRD.md`.

**Line count:** 542 lines (~17,100 words). Structure: §1 Introduction → §2 with 12 subsections → §3 with 9 subsections → §4 endpoint table (4 columns) → §5 error table (2 columns). File ends at §5 with no audit footer.

**Coverage self-check (programmatic, run against the emitted file):**

| Item | Result |
|---|---|
| Endpoints | 70 / 70 rows present in §4; every one also reachable in §2/§3 narrative |
| Errors | 35 / 35 in §5 table, and every `ERR_*` id also appears in §2 or §3 prose at its trigger site |
| Validation rungs | 25 / 25 — rendered as a single ordered engine in §2.6 with rung number, condition, error id, HTTP status and `applies_to` scope |
| Calculations | 13 / 13, all 7 dual-variant ones with the discriminator and both branches named |
| State machines | 10 / 10; all 45 transitions covered (both parallel-axis pairs rendered as independent axes) |
| Entities | 14 / 14 |
| Roles | 7 / 7, each with its `identity:` translated into §2.1 prose |
| Contract 1 (field names) | 165 required identifiers (entity fields + request bodies + query params + path params + response payload keys) — **0 missing** |
| Contract 3 (§3 path purity) | 976 backtick tokens scanned in §3 — 0 leading-slash, 0 bare-method, 0 method+path |
| §2.2 verbatim | byte-identical to `section-2.2-response-structure.md` |

**Nothing was dropped.** No scaffold item was left unrendered.

**Scaffold ambiguities found, and how I resolved them in prose (each stated explicitly so a PRD-only reader cannot diverge):**

1. **Action-level role restrictions had no declared error.** The `BOOKED → NO_SHOW` transition is restricted to `Clinician`, and `CLINIC_MEASURED` assessments to `Clinician`, but neither maps to a rung. Pinned to rung 2 / `ERR_FORBIDDEN_ROLE` (403), stated in §2.1 and again in rung 2's text. A `Participant` naming *another* member on a self-attested row remains rung 5 / `ERR_SCOPE_VIOLATION`.
2. **Supplied-date range constraints had no declared error** — the 30-day retro-termination bound on both participant-terminate and eligibility-record-terminate, the "not earlier than clock" bound on credential renewal, and `shift_end` after `shift_start`. All pinned to rung 7 / `ERR_VALIDATION` (400) and enumerated there. Reinstatement's *grace-window* bound, which is state rather than payload, is pinned to rung 10 / `ERR_INVALID_STATE`, with the ordering against rung 12 stated.
3. **`ENROLLMENT_TERMINATED` is a declared `cancellation_reason` member but has no client trigger.** Stated as system-only; a caller supplying it gets `ERR_VALIDATION` (it passes rung 8 since it *is* a declared enum member).
4. **Reschedule and quota counters.** The scaffold triggers `quota_contract_selection` on reschedule but lists no counter side effects. Resolved explicitly: the selector re-runs and normally re-pins the same contract with no counter movement; if the winner differs, one unit moves (old contract's `quota_visits_consumed` and `quota_visits_requested_total` each −1, new contract's each +1) so quota conservation holds on both.
5. **RAS completion with no covering reporting period.** Cascade hop 3 needs a period containing `measurement_date`. Stated: hops 1–2 land, hops 3–5 do not, no award is created.
6. **`Provider.credential_status` `DEACTIVATED` vs rung 15.** Rung 15 tests for `CREDENTIALED`, so deactivated providers also yield `ERR_PROVIDER_CREDENTIAL_LAPSED` — stated so a reader does not invent a separate code.
7. **Restatement does not unwind pricing.** Not stated in the scaffold either way; pinned — contracts stay `TRUED_UP` with their prior figures and `program_cost_to_date_cents` keeps its booked value until the next finalization adjusts by the delta.
8. **Redirect successors do not auto-authorize.** The scaffold's auto-authorize leg is triggered only at original creation while redirect explicitly creates the successor in `SUBMITTED`; called out as an intentional asymmetry.
9. **Cross-entity `version` bump granularity.** Made uniform and explicit: any resource whose stored attributes the server writes (including pure cascade targets) gets `updated_at` refreshed and `version` +1, at most once per request; a rejected request writes nothing.

**Deliberate opposite-convention sites** are each rendered at their own location *and* collected in §2.10 with a warning against generalising: eligibility spans closed, reporting periods closed, staffing containment closed, operating window closed, provider occupation half-open with zero buffer, day capacity strict-less-than, SLA escalation strict, credential expiry closed at the top. Both gate rungs (3 and 6) have dedicated subsections enumerating exactly which endpoint families they cover, plus the pre-emption ordering. Rounding order is pinned in two places (per-shift hours before summation; per-category avoided cost before summation) and restated in §2.11. Branch-asymmetric non-firing side effects are stated on the failing branch too (revocation not retracting released disclosures, reinstatement not restoring cancellations, no-show not releasing quota, termination not forfeiting `APPROVED`/`EXPORTED`/`PAID` awards, denial writing nothing, cap/budget breach on RAS completion writing nothing).

**Orchestrator independent verification of Step 4:** `PRD.md` = 541 lines / 29 headings; all 35 scaffold error ids present in the PRD text (0 missing); all 70 scaffold endpoint paths present (0 missing); leak check — the strings `SCAFFOLD`, `DIFFICULTY_DESIGN`, `CORNER_DESIGN` appear nowhere in the PRD.

## Step 5: Generate unit tests — 2026-08-03T19:12:00.000Z

Test infrastructure and suite are complete and self-checked.

**Output** — `test_helpers/` (9 files) and `test_suite/` (conftest + 13 test files), 6,303 lines total.

**Tests: 87** across 13 files (test_01 program setup 9, test_02 eligibility/enrollment 8, test_03 credentialing 5, test_04 appointment geometry 11, test_05 quota/slot conservation 4, test_06 encounter axes 10, test_07 HRA scoring 7, test_08 alternative standards 4, test_09 referrals 5, test_10 incentives 6, test_11 reporting 8, test_12 access control/ladder gates 8, test_13 OCC 2).

**Coverage: queue A 23/23 instances (every one with exactly 2 tests, 46 total); queue B 41/41 non-stub instances (1 test each). Zero instances skipped** — every instance passed the PRD-first two-condition filter. The 3 `excluded_because` stubs were not translated; all 3 `difficulty_instance` cross-references resolve.

**Design-index recipes corrected toward the PRD (2):**
1. `Difficulty/non_linear_state_machine/referral_decline_redirect_cycle_spawns_successor_without_double_counting` asserts the successor is `AUTHORIZED` "because CENTER_OF_EXCELLENCE auto-authorizes at creation". PRD §3.7 says the opposite: *"it starts at `SUBMITTED` **whatever its `steerage_tier`**: the auto-authorization that applies at original creation does not apply to a redirect successor"*. Tests assert `SUBMITTED`.
2. `Corner/consistency_model/cancellation_cascade_is_visible_immediately_in_the_same_request` cancels `as: CareNavigator` while passing the *clinician's* provider id — PRD §2.1 makes that an `ERR_SCOPE_VIOLATION` (a `CareNavigator` whose backing Provider is `CLINICIAN`). The test creates a real NAVIGATOR provider and cancels under its id.

**Self-check numbers:** (a) 87 `def test_` == 87 `Design:` tag lines; (b) all 87 tags resolve to real instance names with matching rule_id/section, zero malformed, zero dual-tagged, zero stub-tagged; (c) 0 `skip`/`skipif`/`xfail` markers; (d) 0 test bodies without an assertion construct; (e) `ast.parse` + `py_compile` clean over all 23 emitted files, pyflakes clean over `test_suite/`, `pytest --collect-only` collects 87. Bonus: all **169** PRD quotations were machine-verified verbatim against `PRD.md` (whitespace-normalized) — one was rewritten after the check caught a paraphrase.

**Fixture ordering around the two gate rungs** (documented in `fixtures.py`'s module docstring):
- *Rung 6 (period freeze)* — `setup_clinic` only ever **opens** a period (`OPEN` does not freeze) and does so as its last step; `finalize_period()` is a separate helper a test calls only after all its clinical writes have landed. The freeze tests (`test_12`) therefore build → complete → advance clock → finalize, so `ERR_PERIOD_FINALIZED` is genuinely the first failing rung rather than an artifact of setup.
- *Rung 3 (confidentiality wall)* — every clinical read inside a fixture (`read_visit`, assessment/referral/RAS reads) is made by a clinic-side role or `ProgramAdmin`; a grep confirms the only employer-side call on the eight walled routes is the deliberate wall test itself.

**Other hazard handling:** `parse_instant`/`assert_same_instant` in `assertions.py` compare every datetime semantically (all `...Z` vs `...000Z` assertions go through them); the four opposite boundary conventions are asserted at their own PRD sites rather than via a shared `overlaps()`; segregation-of-duties uses two genuinely distinct NAVIGATOR providers (`navigator_count=2`); and `test_users.py` exposes per-instance builders for all four entity-backed roles so no `X-User-ID` is ever shared across two entities the PRD requires to be distinct.

## Step 6: Generate implementation — 2026-08-03T19:12:00.000Z

The implementation is complete and verified.

**29 Python modules, 5,041 lines** (5,056 including `start.sh` + `requirements.txt`):
- `app.py` — app factory, registers all 70 specs through one dispatcher
- `core/` (11) — `constants`, `timeutil`, `errors`, `payload`, `envelope`, `store`, `serializers`, `calc`, `recompute`, `ladder`, `__init__`
- `routes/` (17) — one module per resource group, each exporting declarative `Spec` objects

In-memory dicts only; no seeding, no persistence, no `/tmp` cache. `start.sh` guards its pip install, reads `$PORT`, binds `0.0.0.0`, `exec`s in the foreground. Cold-boot over HTTP verified (200 envelope on `GET /sites`, 401 envelope unauthenticated).

**Endpoint completeness gate: scaffold 70 / registered 70 / MISSING 0 / EXTRA 0** — diffed programmatically with path params normalized to positional markers on both sides (`{id}` vs `<participant_id>`), `/static` excluded.

**Adjudication 1 — timestamp rendering.** Rule: one canonical rendering, `YYYY-MM-DDTHH:MM:SS.mmmZ`, for every datetime the API emits. Every inbound instant (`shift_start`, `shift_end`, `scheduled_start`, `to_iso8601`) is parsed and re-rendered through `core/timeutil.fmt_instant` at ingest, so caller input round-trips in exactly the same shape as `created_at`. Enforced in one place: `timeutil.fmt_instant`, plus `store.set_clock` which normalizes the clock before anything reads it. Justification: PRD §2.4 mandates three fractional digits for `created_at`/`updated_at` and §3.7 mandates them for `sla_due_at`; no PRD sentence asks for a literal echo, so echoing verbatim would put two spellings inside one payload. **Hit this exact bug during the build**: `store._clock_iso` was initialized straight from the constant `"2026-05-01T00:00:00Z"`, so the very first `created_at` came back without `.000`. Fixed by routing the initial reading through `fmt_instant`.

**Adjudication 2 — enum-membership routing.** Rule: every enum-valued input on a write endpoint reports membership failure as `ERR_INVALID_ENUM` at rung 8 — not only the thirteen the PRD prose names. **14 distinct enum fields across 17 endpoint×field sites.** The field beyond the PRD's list is `fitness_conclusion` (on visit complete and visit amend). Two deliberate exclusions: enum-valued **query filters** on GET list endpoints are not routed (rung 8 says "every write endpoint"), and `cancellation_reason = ENROLLMENT_TERMINATED` is a *declared member*, so §3.4's refusal of it fires at rung 7 as `ERR_VALIDATION`, above rung 8.

**The 25-rung ladder.** One ordered engine in `core/ladder.py`. Rungs 1–9 are generic and data-driven off `Spec`; rungs 10–25 are per-endpoint callables held in `Spec.checks` keyed by rung number and executed by `sorted(ctx.spec.checks)`, so an endpoint structurally cannot evaluate rung 20 before rung 17. Every route goes through `make_view` → `run_ladder` → handler.
- **Rung 3** is a `spec.walled` flag tested before `rung4_existence` ever looks at the path id — a walled read of a nonexistent id returns the wall error (verified), and `PayrollProcessor` is refused earlier at rung 2 as the PRD requires.
- **Rung 6** is a `spec.freeze` callable that runs before payload, enum, OCC and state. Verified: a malformed amend inside a FINALIZED period reports `ERR_PERIOD_FINALIZED`, as does one carrying a stale version.
- Also verified structurally: rung 9 beats rung 15/16, rung 11 beats every scheduling rung, rung 24 beats rung 25, rung 13 beats rung 14.

**Conservation invariants.** All three live in `core/recompute.py` and are **re-derived from the rows they partition**, never incrementally adjusted, so no write path can drift them: `recompute_period_buckets` (incentive money — award create/approve/export/mark-paid/reverse, the termination forfeit leg, RAS cascade hop 4, finalize); `recompute_site_counters` (site slots — booking, cancel, no-show, check-in, reschedule, termination cascade hop 3); `recompute_contract_quota` (employer quota — booking, cancel, reschedule re-pin, termination cascade hop 4). Version-bump granularity is central too: `store` snapshots the whole store per request, diffs each pre-existing row at commit, and applies **exactly one** `version`+`updated_at` bump per changed resource; a rejected request restores the snapshot verbatim. Two declared-unconditional bumps (site PATCH, reschedule) use `force_version_bump` because no stored attribute changes.

**Ambiguities and the reading adopted:**
1. **Rung 5 on single-resource GETs.** The PRD lists only write verbs but rung 5 says it "applies to every endpoint acted on by" the four entity-backed roles. Ownership enforced on single-resource GETs as well as writes. **List endpoints are neither rejected nor filtered** — no PRD sentence authorizes scoping a collection.
2. **Clinician ownership scope.** `visit.provider_id == X-User-ID` is enforced only on the four *advancing* writes (§3.5 verbatim), not on reads and not on check-in (§3.4: "the acting clinician does not have to be the appointment's own provider").
3. **Reschedule quota selector.** Run literally, unmodified — the currently pinned contract is subject to the same strict `consumed < total` filter.
4. **"Writes an attribute" with an unchanged value.** Diff-based: a recompute yielding an identical value does not bump `version`.
5. **Pagination out of range.** No error code exists for `limit=0` or `limit=500`, so values are clamped into the declared window rather than rejected.
6. **RAS completion with no covering period.** §3.6 says the first two effects land and the last three do not; rungs 24/25 are therefore also skipped, since there is no award to price against the cap.

Three self-written smoke suites (scratchpad only, not test-suite files) covering ~230 assertions all pass.

**Orchestrator independent verification of Steps 5+6:** `def test_` count 87 == `Design:` tag count 87 == `pytest --collect-only` 87; `grep -rn "skip\|xfail"` over both test dirs returned 3 hits, all read individually and all the English words "skip"/"skips" inside docstrings/parameter prose — zero markers; `ast.parse` clean over all 23 test files + all 29 impl modules; impl grep for `sqlite|pickle|shelve|json.dump|open(...,'w')|/tmp` **empty**; **live** boot of `app.url_map` diffed against scaffold `endpoints[]` with path params normalized → scaffold 70 / registered 70 / MISSING 0 / EXTRA 0 (independently reproduced, not taken from the subagent's report).

## Step 7: Run tests and iterate — 2026-08-03T19:27:00.000Z

All 87 tests intact (none deleted, none skipped), 8/8 rounds green.

**Iterations run:** 3 sweeps (8 rounds each, 2 waves of 4, `sweep.sh` unmodified).

**Tests deleted:** none. Every failure traced to a real defect on one side or the other; no test hit a PRD-silence or unique-derivability collapse.

**Fixes applied to `implementation/`:**
- `core/store.py` — `Txn.__init__` / `commit()` / new `register_projection()`. Response payloads were being projected from live rows *inside the handler*, i.e. before `commit()` applied the at-most-once version bump, so every mutating response reported a stale `version` and `updated_at`. `commit()` now re-syncs each registered projection from its row after bumping. PRD §2.4: "Every stored attribute of a resource is response-visible … by any operation that mutates the resource."
- `core/serializers.py` — `dump()` / `dump_many()` register their projections with the transaction so `commit()` can refresh them.
- `start.sh` — dependency probe changed from `import flask` (~0.24s) to `importlib.util.find_spec('flask')` (~0.02s). Identical install-only-when-missing semantics, `exec` still the final command; boot 0.57s → ~0.35s.

**Fixes applied to `test_suite/`:**
- `test_01_program_setup_and_registry.py::test_site_listing_pages_and_filters_by_host_employer` — asserted `has_more is False` for `offset=1, limit=1` over 3 matching sites. PRD §2.3 defines `has_more` as "true when records matching the filters remain beyond the current page"; the third site remains, so the correct expectation is `True`. Test bug, made more faithful rather than relaxed.

**Fixes applied to `test_helpers/`:** none needed — the large `ERR_STALE_VERSION` batch in `test_06`/`test_13` looked like the classic upstream-fixture masquerade flagged in the triage hint, but tracing it end-to-end showed the fixtures were correct and were faithfully echoing a version the server had under-reported. The single `store.py` fix cleared all of them.

**Key finding on the flaky round:** sweep 2 showed 6 scattered non-deterministic failures, all `ERROR at setup` — "API server could not be restarted", each at exactly the runner's 15.0s poll ceiling, on a different test each round. These were *not* test or implementation defects: three sibling PRD-bench pipelines (`task_0917`, `task_0918`, `task_0921`) were running 8 concurrent rounds on the same 8-core host. Cutting boot time restored the margin — sweep 3 went fully green at load average **9.34**, higher than the 4.59 at which sweep 2 flaked, which is what distinguishes a real fix from a lucky round.

**Per-round wall-clock and final results:**

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Wall-clock | 84.5s | 86.3s | 85.4s | 86.5s | 55.2s | 55.2s | 54.9s | 54.9s |
| Result | 87/87 | 87/87 | 87/87 | 87/87 | 87/87 | 87/87 | 87/87 | 87/87 |

0 failed, 0 errors, 0 skipped in every round.

**Orchestrator independent verification of Step 7:** re-parsed all 8 `results.N.json` myself — each has **87 individual result rows** (not just an aggregate counter), status distribution `{'passed': 87}` in every round, and the sorted test-name lists are **byte-identical to round 1 in all 7 comparisons** (87 distinct names). Post-fix re-checks: `def test_` count 87 == `Design:` tag count 87 (no test lost in the Step-7 edit); impl grep for `sqlite|pickle|shelve|json.dump|/tmp` still empty after the `store.py`/`serializers.py` edits.

## Step 8: Finalize PRD — 2026-08-03T19:32:00.000Z

`PRD_FINALIZED.md` written. **One edit total.**

**Line counts:** `PRD.md` 541 lines / 17,107 words / 122,087 chars → `PRD_FINALIZED.md` 541 lines / 17,157 words / 122,403 chars. Delta **0.0% by line**, **+0.29% by word**.

**Change:** §2.4 Common Resource Properties, Timestamps and Versioning — *insert* — one sentence pinning that a mutating operation's returned resource payload shows the resource **as it stands at the end of that request** (`version`/`updated_at` are post-write values already reflecting whatever single increment/refresh that request produced) — `core/store.py:100-123` (`commit()` re-syncs registered projections after the at-most-once bump), `core/serializers.py:96-109`, `core/store.py:126-130`.

**Pre-edit search log (edit 1):** (a) subject = the `version`/`updated_at` values carried by any mutating request's response payload. (b) paths enumerated — `store.py` `Txn.__init__`/`commit()`/`register_projection()`/`insert()`/`rollback()`/`force_version_bump()`; `serializers.py` `_base()` + all 14 per-kind projectors + `dump`/`dump_many` + `eligibility()` read-time derivation; `ladder.py` `make_view()` ordering and `paginate()`; all 60+ `ObjectResult(serializers.dump(...))`/`paginate(...)` return sites across the 15 route modules; the two force-bump paths (`sites.py:79`, `appointments.py:200`); the create-then-return paths where commit deliberately does not bump (`appointments.py:316` check-in Visit, `referrals.py:154` relink successor, all 14 POST creators); the non-resource payloads outside scope (`ops.py:55`, `calc.py:234`, `periods.py:338`); and the cascade-only mutations absent from the response. (c) three wording adjustments, all to avoid over-claiming: scoped the claim to "the payload it returns"; wrote "whatever single increment … this request produced" so creates correctly stay at version 1; dropped a "never the values it held before the request" tail that would have misdescribed endpoints returning a row created during the request.

**Deliberately not patched:** `has_more` — `core/envelope.py:44` computes `(offset + len(items)) < total_count`, exactly PRD §2.3's verbatim wording, so the Step-7 item was a pure test-side bug and prose stayed verbatim (search performed over `envelope.py:39-50`, `ladder.py:294-299`, `read_pagination()`, all 13 `paginate` callsites). `start.sh` boot probe — not PRD-visible. `test_helpers/` — no fixes were applied there.

## Step 9: Complete PRD — 2026-08-03T19:45:00.000Z

**File sizes:** `PRD_FINALIZED.md` 541 lines / 122,403 chars → `PRD_COMPLETED.md` 547 lines / 139,501 chars (**+6 lines, +17,022 chars**). The 6 new lines are three inserted paragraphs (each + blank separator) inside existing sections; no new headings, no new sections.

**Heading-structure diff:** empty. 29 headings, 109 table rows, 25 ladder rungs unchanged.

**Counts: 30 ambiguity-pins, 2 mismatch-revisions (32 edits).**

- §2.1 — insert — ambiguity — a `Clinician`/`CareNavigator` whose `X-User-ID` resolves to no `Provider` at all also gets `ERR_SCOPE_VIOLATION`, and that identity half of rung 5 runs on *every* endpoint — `core/ladder.py:158-162`
- §2.3 — insert — ambiguity — pagination is clamped, never rejected: `limit`≤0→1, >100→100, `offset`<0→0, unparseable→default; `offset` past `total_count` yields an empty page — `core/envelope.py:62-86`
- §2.3 — insert — ambiguity — insertion order is the `created_at` tie-break; `id` is never a sort key; every list uses the one ordering — `core/store.py:218-226`
- §2.3 — insert — ambiguity — filters are exact, case-sensitive raw-string matches; empty string never filters; an off-enum filter value returns an empty page, not `ERR_INVALID_ENUM`; lists are never identity-narrowed — `routes/common.py:48-55`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum characters — `core/envelope.py:19-20`
- §2.4 — insert — ambiguity — **one canonical instant rendering** `YYYY-MM-DDTHH:MM:SS.mmmZ` for server stamps, computed instants *and* caller-supplied instants (re-rendered at ingest); liberal inbound grammar (`T`/`t`, `Z`/`z`/±offset, 1–9 fraction digits); date-only and `HH:MM` fields stay as-is — `core/timeutil.py:1-82`
- §2.4 — insert — ambiguity — rows created by the request stay at `version` 1; a recompute landing on the stored value is not a write (no bump); the exactly two unconditional force-bump paths are the site PATCH and the reschedule — `core/store.py:100-154`
- §2.4 — insert — ambiguity — every declared key is always emitted (unset ⇒ JSON `null`, never omitted); an optional input supplied as `null` is treated as absent; unknown body keys ignored — `core/serializers.py:16-17`, `core/payload.py:15-17`
- §2.4 — insert — ambiguity — body FKs resolve in the order §3 introduces them; absent/`null`/non-string ids are not looked up at rung 4 — `core/ladder.py:142-151`
- §2.5 — insert — ambiguity — sweep id lists are creation-ordered; the clock accepts any parseable instant (no monotonicity); the response is a 4-key computed payload, not a resource — `routes/ops.py:13-63`
- §2.6 rung 5 — insert — ambiguity — full enumeration of where the participant / employer / provider ownership comparisons engage, and where they explicitly do not (lists, site/provider/shift single reads, check-in, all referral actions) — `routes/*.py` `scope=` declarations
- §2.6 rung 7 — insert — ambiguity — required strings have no minimum length except `employer_code`; the empty string is accepted for the nine named fields — `core/payload.py:30-38`
- §2.6 rung 8 — **revise — mismatch** — `fitness_conclusion` added as the **fourteenth** enum-routed field (PRD listed 13; impl routes it on visit complete *and* amend) — `core/constants.py:95-129`, `routes/visits.py:224,237`
- §2.6 rung 8 — **revise — mismatch** — enum type-assertion is non-uniform: on the six named creation endpoints a non-string enum value passes rungs 7 and 8 and is stored; everywhere else it is `ERR_VALIDATION` at rung 7 — `routes/sites.py:11`, `contracts.py:13`, `providers.py:13`, `shifts.py:15`, `eligibility.py:16`, `appointments.py:135`
- §2.6 rung 12 — revise — ambiguity — on a reschedule the governing date is the one implied by the **new** `scheduled_start` — `routes/appointments.py:31,45`
- §2.12 — revise — ambiguity — the three invariants are **re-derived from rows**, never incrementally adjusted — `core/recompute.py:1-92`
- §2.12 ×3 — insert — ambiguity — the exact write paths that trigger each of the three recomputes (money / slots / quota) — `core/recompute.py` call sites
- §3.1 — insert — ambiguity — `operating_weekdays` non-empty ints 1–7; `HH:MM` two-digit shape; no open/close ordering constraint — `core/payload.py:133-161`, `routes/sites.py:12-14`
- §3.1 — revise — ambiguity — the site PATCH bumps `version` unconditionally, even with no revisable field or identical values — `routes/sites.py:79`
- §3.3 — insert — ambiguity — eligibility termination is repeatable, replaces the date, and does not re-test rung 23; the `coverage_status` filter is evaluated against the clock date — `routes/eligibility.py:65-68,89-94`
- §3.3 — insert — ambiguity — the termination response echoes the participant alone, not the cascaded rows — `routes/participants.py:136`
- §3.3 — revise — ambiguity — revocation also leaves `NOT_DISCLOSABLE` and already-`SUPPRESSED` visits untouched — `routes/participants.py:201-205`
- §3.4 — revise — ambiguity — the quota waterfall's final tie-break is insertion order — `core/calc.py:300`
- §3.5 — insert — ambiguity — disclosure-release is likewise reserved to the visit's own provider (rung 5) — `routes/visits.py:248`
- §3.6 — insert — ambiguity — omitted assessment metrics store and return `null` — `routes/assessments.py:81-87`
- §3.6 — insert — ambiguity — where several periods contain the measurement date, the earliest-created takes the retroactive award — `routes/alt_standards.py:40-41`
- §3.6 — insert — ambiguity — with no containing period the cap and budget rungs do not engage; the response carries the request alone — `routes/alt_standards.py:171,180`
- §3.8 — revise — ambiguity — approval and export move no money, so no period / employer / participant `version` advances — `routes/awards.py:14-23`
- §3.8 — revise — ambiguity — on mark-paid only the period moves (a paid award still commits budget) — `core/constants.py:168`
- §3.8 — insert — ambiguity — `incentive_awarded_cents` sums all statuses, so no settlement transition ever bumps a participant — `core/recompute.py:102-107`
- §3.9 — insert — ambiguity — finalization moves no participant (`LOCKED` still counts as delivered); the period's buckets re-derive unchanged; the response is the period alone — `routes/periods.py:178-181`
- §3.9 — insert — ambiguity — no ordering constraint on `period_start`/`period_end`, and periods of one employer may overlap — `routes/periods.py:43-47`
- §3.7 — insert — ambiguity — a redirect successor starts with its four audit fields null — `routes/referrals.py:148-151`
- §4 — insert — ambiguity — unknown route *and* method mismatch both answer `ERR_RESOURCE_NOT_FOUND`/404; trailing slashes are accepted — `app.py:62,72-82`

**Checklist categories that came back genuinely clean** (already uniquely pinned by the source PRD): **all boundary-inclusivity sites** — eligibility closed span, reporting-period closed span, staffing closed containment, operating-window closed, provider occupation half-open with zero buffer, day capacity strict-`<`, SLA escalation strict, credential expiry closed-at-top, the 30-day grace bounds, RAS due-date closed, `finalize` requiring clock strictly past `period_end`, cap/budget inclusive bounds, `shift_end` strictly after `shift_start` — every `<`/`<=` in the impl was matched by prose at its own location. Also clean: **all 13 calculations and their rounding order** (per-shift hours rounded before summing, per-category avoided cost rounded before summing, 4-dp ratios, half-up cents, the 1.25 self-attest multiplier, zero-denominator rules); **the depth-5 RAS cascade's negative branches** plus the termination cascade's `APPROVED`/`EXPORTED`/`PAID` exclusion, revocation-not-retracting, reinstatement-not-compensating, no-show-not-releasing-quota, denial-writing-nothing, cap/budget-breach-writing-nothing; **both gate rungs' coverage sets** (the eight walled routes and seven frozen writes match the impl exactly); **OCC** (three endpoints, correct parents, rung 9); **server-side defaults**; and the **utilization report's suppression rules and key ordering**.

**Orchestrator independent verification of Step 9:** `PRD_COMPLETED.md` = 547 lines; heading structure `diff` against **both** `PRD_FINALIZED.md` and the original `PRD.md` is **empty** (29 headings each); all 35 scaffold error ids and all 70 endpoint paths still present in the completed document (0 missing); leak check — `SCAFFOLD`, `DIFFICULTY_DESIGN`, `CORNER_DESIGN` appear nowhere.

---

**Orchestrator independent verification of Step 2:** all 3 files `yaml.safe_load` clean; `SCAFFOLD.yaml` top-level counts confirmed (14 entities / 10 state_machines / 3 concurrency_rules / 3 conservation_invariants / 13 calculations / 25 validations / 70 endpoints / 35 errors / 7 roles / 49 global_constants); ladder priorities contiguous 1..25 with no gaps or duplicates; independent ALL_CAPS sweep found 113 distinct tokens, 30 residual after subtracting declared constants + enum members + error codes + state names — all 30 manually confirmed to be enum members (visit_type, biometric source, fee model, steerage tier, fitness conclusion, …) except the two design-file names and one `ERR_XXX` placeholder inside the response-envelope illustration. **Zero valueless constants.**
