
## Step 8: Finalize PRD — 2026-09-01T02:50:00.000Z

Not skipped: Step 7 applied 2 `implementation/` fixes, 3 `test_suite/` fixes and 1 `test_helpers/` fix, so the skip condition (zero iterations beyond baseline) did not hold.

Subagent summary (verbatim):

Three targeted edits applied. Final verification of consistency for each edit's subject is complete.

## Summary

**Line counts:** PRD.md 540 lines -> PRD_FINALIZED.md 540 lines (0.0% line delta; 3 lines revised in place, no lines added or removed).

### Changes

- **§2.7 rung 18 — revise —** `ACTIVE` gate re-scoped from the ambiguous "milestone attainment" to "the explicit creation of a milestone attainment row", with an explicit note that the attest/revoke/reopen decisions do not re-check `program_status` — `implementation/routes_attainments.py:33-34` (gate on `POST /milestone-attainments`), absent from `decide_attainment` (`routes_attainments.py:85-154`).
- **§3.5 "The phase dimension" — revise —** forward phase steps are drivable by the mentor on the match **or** the `SiteInductionLead` of the novice's site (PRD had attributed all three forward steps to the mentor alone) — `implementation/routes_observations.py:126-139`.
- **§3.7 "Attainment rows carry the progress" — revise —** initial status rule widened: a row opens `IN_PROGRESS` when its milestone names no prerequisite **or when the prerequisite's attainment row for that novice already stands `ATTAINED`**, `LOCKED` otherwise; noted that at enrolment this still means every prerequisite-bearing milestone seeds `LOCKED` — `implementation/cascades.py:8-38`.

### Per-edit pre-edit search log

**Edit 1 (§2.7 rung 18)**
- (a) Subject: which novice `program_status` gate attaches to which attainment operation.
- (b) Enumerated: `grep -rn NOVICE_PROGRAM_STATE_INVALID implementation/` -> `routes_attainments.py:34` (create only), `routes_observations.py:47`, `routes_novices.py:121`, `routes_matching.py:78,210,212`, `routes_packets.py:33,177`. Read `routes_attainments.py` in full (create *and* decision handlers) to confirm attest/revoke/reopen carry no program-status check; confirmed the create-time check sits after fk/validation/ownership and before the duplicate check, matching ladder order 18 < 40. Checked §3.7 attestation prose (line 347) and §3.9/§3.1 for a competing program-status claim about attainments — none.
- (c) Adjustment: scoped the wording to *explicit* creation so it cannot be read as covering enrolment seeding (`routes_novices.py:57-58` seeds rows while the novice is still `ENROLLED`); left the packet-creation clause untouched despite the separate §3.9/rung-18 tension (out of scope).

**Edit 2 (§3.5 phase dimension)**
- (a) Subject: who may request observation-cycle phase moves.
- (b) Enumerated: `routes_observations.py` `advance_cycle` (guard `[MENTOR, LEAD]`, mentor->`own_mentor`, lead->`own_site`, applies to `OBSERVED`/`POST_CONFERENCE`/`DOCUMENTED`/`ABANDONED`), `write_feedback` (guard `[MENTOR]` only), feedback-review guard, `create_cycle` guard `[MENTOR, LEAD]`, `cascades.abandon_cycles()` (roleless cascade abandonment), §4 table rows for `/observation-cycles/{id}/advance`, `/feedback`, `/feedback-review`, and test_208's lead-driven `OBSERVED` advance.
- (c) Adjustment: worded as "either the mentor ... or the `SiteInductionLead` of the novice's site" so it neither admits `ProgramAdmin` (impl returns 403) nor disturbs the mentor-only feedback-authoring sentence; kept the "each requires the match to still be `ACTIVE`" clause attached to the three forward steps only, since the `ABANDONED` path in impl deliberately skips that check.

**Edit 3 (§3.7 initial attainment status)**
- (a) Subject: the status an attainment row is born in.
- (b) Enumerated: `cascades.create_attainment()` (the single writer of initial status, called from both `routes_novices.py:57-58` enrolment seeding and `routes_attainments.py:38` explicit creation), `cascades.unlock_dependents()` / `relock_dependents()` (later `LOCKED <-> IN_PROGRESS` moves), the REOPEN branch in `decide_attainment` (`IN_PROGRESS` with prerequisite-`ATTAINED` precondition), `domain.attainments_of_novice()` ordering, and `domain.milestones_sorted()` seeding order.
- (c) Adjustment: added the trailing clause about enrolment so the widened rule cannot be misread as changing seeding behaviour (at enrolment no row can yet be `ATTAINED`, so prerequisite-bearing milestones still seed `LOCKED`); phrased the fallback as "and `LOCKED` otherwise" so the case where the prerequisite milestone has no row at all for that novice is still covered.

### Items requiring no PRD change
- `test_helpers/fixtures.py` fallback to `POST /milestone-attainments` — PRD §3.7 already licenses that path (fixture bug); only the two derived silences above were pinned.
- `test_202` stipend accrual (4200 cents) — §3.8/§3.4 already pin the `SUBMITTED`-or-`VERIFIED` input set, live tier/multiplier, projected-and-capped minutes and the refresh-on-submission trigger; `domain.provisional_accrual()` matches verbatim prose.
- `test_206` `credited_seminar_sessions == 0` on a still-`SCHEDULED` session — §3.6 explicit; `domain.recompute_novice_evidence()` matches.
- `test_208` clock/window rebooking — §3.5 (clock >= `window_end`) and §2.11 (closed intervals, +30 min each side, "a gap of 31 minutes is accepted") already pin `calc.observation_conflict()` exactly.
- Three 404 identifier renames — §2.7 rung 5 and the §5 closed catalogue already mandate `ERR_SEMINAR_SESSION_NOT_FOUND`, `ERR_SEMINAR_ATTENDANCE_NOT_FOUND` and (for the `/completion-certifications` collection) `ERR_CERTIFICATION_NOT_FOUND`; impl was fixed to the PRD.
- `cascades.revoke_unsupported_attainments()` decrement — §3.7 line 351 already requires a revocation to decrement `attained_milestone_count`, and the void route's "refresh counters, cascade, re-derive snapshot" order leaves the decremented value equal to a recount, so no wording change was warranted.

Orchestrator verification: PRD_FINALIZED.md is 540 lines (same as PRD.md); `diff` shows exactly 3 changed lines (139, 311, 345) with 0 insertions/deletions of whole lines; heading count identical, confirming no new sections.
