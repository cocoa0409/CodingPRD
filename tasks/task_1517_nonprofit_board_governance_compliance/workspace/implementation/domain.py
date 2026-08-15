"""Domain logic: computed fields, calculations, state machines, cascades, sweep."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import store
from helpers import add_months, add_years, iso, last_day, new_entity, now_iso, touch

SKILL_TAGS = ['FINANCE', 'LEGAL', 'FUNDRAISING', 'PROGRAM', 'GOVERNANCE',
              'MARKETING', 'TECHNOLOGY', 'HR']
OFFICER_ROLES = ['NONE', 'CHAIR', 'TREASURER', 'SECRETARY']
COMMITTEE_TYPES = ['AUDIT', 'FINANCE', 'GOVERNANCE', 'NOMINATING', 'EXECUTIVE',
                   'COMPENSATION', 'OTHER']
MOTION_CATEGORIES = ['GOVERNANCE', 'FINANCE', 'PERSONNEL', 'POLICY', 'BYLAWS',
                     'FUNDRAISING', 'OTHER']
MOTION_THRESHOLDS = ['SIMPLE_MAJORITY', 'TWO_THIRDS', 'UNANIMOUS']
MOTION_BASES = ['PRESENT_AND_VOTING', 'FULL_QUORUM', 'FULL_BOARD']
VOTE_CHOICES = ['AYE', 'NAY', 'ABSTAIN', 'RECUSED']
EVAL_DIMENSIONS = ['LEADERSHIP', 'FUNDRAISING', 'FINANCIAL', 'PROGRAM', 'GOVERNANCE']
EVAL_WEIGHTS = {'LEADERSHIP': Decimal('0.30'), 'FUNDRAISING': Decimal('0.20'),
                'FINANCIAL': Decimal('0.20'), 'PROGRAM': Decimal('0.20'),
                'GOVERNANCE': Decimal('0.10')}
TARGET_ROLES = ['EXECUTIVE_DIRECTOR', 'BOARD_CHAIR', 'TREASURER']
READINESS = ['READY_NOW', 'ONE_YEAR', 'TWO_PLUS_YEARS']
POLICY_TYPES = ['DNO', 'GENERAL_LIABILITY']
BYLAWS_KNOBS = ['quorum_pct', 'quorum_basis', 'amendment_threshold_pct',
                'term_length_years', 'max_consecutive_terms', 'term_cooloff_years',
                'board_size']

# Restricted motion category -> committee types whose appointments end.
RESTRICTION_MAP = {
    'FINANCE': {'FINANCE', 'AUDIT', 'COMPENSATION'},
    'PERSONNEL': {'COMPENSATION', 'EXECUTIVE'},
    'GOVERNANCE': {'GOVERNANCE', 'NOMINATING'},
}

BUFFER = timedelta(minutes=30)


# ---------------------------------------------------------------- fiscal calendar
def current_fiscal_year(np):
    t = store.get_clock()
    m = np['fiscal_year_end_month']
    return t.year if t.month <= m else t.year + 1


def fy_start_dt(np, fy):
    m = np['fiscal_year_end_month']
    if m == 12:
        d = date(fy, 1, 1)
    else:
        d = date(fy - 1, m + 1, 1)
    return datetime.combine(d, time(0, 0), tzinfo=timezone.utc)


def fy_end_dt(np, fy):
    m = np['fiscal_year_end_month']
    d = date(fy, m, last_day(fy, m))
    return datetime.combine(d, time(0, 0), tzinfo=timezone.utc)


def filing_due_date(np, fy):
    """First day of month after fiscal-year end + 4 months + 14 days."""
    fe = fy_end_dt(np, fy)
    if fe.month == 12:
        base = datetime(fe.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        base = datetime(fe.year, fe.month + 1, 1, tzinfo=timezone.utc)
    return add_months(base, 4) + timedelta(days=14)


# ---------------------------------------------------------------- lookups
def adopted_bylaws(np_id):
    for b in store.bylaws.values():
        if b['nonprofit_id'] == np_id and b['status'] == 'ADOPTED':
            return b
    return None


def active_members(np_id):
    return [m for m in store.members.values()
            if m['nonprofit_id'] == np_id and m['status'] == 'ACTIVE']


def open_seats(np_id):
    b = adopted_bylaws(np_id)
    if b is None:
        return None
    return b['board_size'] - len(active_members(np_id))


def disclosure_for(member_id, fy):
    for d in store.disclosures.values():
        if d['board_member_id'] == member_id and d['fiscal_year'] == fy:
            return d
    return None


def has_active_restrictions(member):
    np = store.nonprofits.get(member['nonprofit_id'])
    if np is None:
        return False
    d = disclosure_for(member['id'], current_fiscal_year(np))
    return d is not None and d['status'] == 'RESTRICTIONS_IMPOSED'


def member_chain(member_id):
    """Trailing adjacency run of the member's terms (all statuses count)."""
    terms = [t for t in store.terms.values() if t['board_member_id'] == member_id]
    terms.sort(key=lambda t: (t['start_date'], t['_seq']))
    run = []
    for t in terms:
        if run and t['start_date'] == run[-1]['end_date']:
            run.append(t)
        else:
            run = [t]
    return run


def chain_index_of(term):
    terms = [t for t in store.terms.values()
             if t['board_member_id'] == term['board_member_id']]
    terms.sort(key=lambda t: (t['start_date'], t['_seq']))
    run = []
    for t in terms:
        if run and t['start_date'] == run[-1]['end_date']:
            run.append(t)
        else:
            run = [t]
        if t['id'] == term['id']:
            return len(run)
    return 1


def committee_active_count(committee_id):
    return sum(1 for a in store.appointments.values()
               if a['committee_id'] == committee_id and a['status'] == 'ACTIVE')


def motion_tallies(motion_id):
    f = n = a = r = 0
    for v in store.votes.values():
        if v['motion_id'] != motion_id:
            continue
        if v['choice'] == 'AYE':
            f += 1
        elif v['choice'] == 'NAY':
            n += 1
        elif v['choice'] == 'ABSTAIN':
            a += 1
        elif v['choice'] == 'RECUSED':
            r += 1
    return f, n, a, r


def disclosure_overdue(f):
    if f['status'] != 'FILED' or f['filed_on'] is None:
        return False
    return store.get_clock() > f['filed_on'] + timedelta(days=30)


# ---------------------------------------------------------------- renewal fee
def _round_half_up_int(x):
    return int(x.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def fee_base(E):
    if E <= 2_500_000:
        return 5_000
    if E <= 10_000_000:
        return 15_000
    if E <= 50_000_000:
        return 30_000
    over = E - 50_000_000
    units = (over + 100_000 - 1) // 100_000  # ceil to started $1,000 increments
    return 50_000 + units * 1_000


def renewal_fee(np, contributions, lapsed):
    """contributions: int or None (None -> ESTIMATED variant)."""
    if contributions is not None:
        E = contributions
    else:
        E = _round_half_up_int(
            Decimal(np['annual_gross_receipts_cents']) * Decimal('0.1'))
    subtotal = fee_base(E)
    late = _round_half_up_int(Decimal(subtotal) * Decimal('0.1')) if lapsed else 0
    return subtotal + late


def coverage_floor(np):
    r = np['annual_gross_receipts_cents']
    return (r + 3) // 4  # ceil(0.25 * r)


# ---------------------------------------------------------------- compliance posture
def compliance_posture(np):
    t = store.get_clock()
    np_id = np['id']
    regs = [r for r in store.registrations.values() if r['nonprofit_id'] == np_id]
    filings = [f for f in store.filings.values() if f['nonprofit_id'] == np_id]
    pols = [p for p in store.policies.values() if p['nonprofit_id'] == np_id]

    # NON_COMPLIANT
    if any(r['status'] == 'LAPSED' for r in regs):
        return 'NON_COMPLIANT'
    cfy = current_fiscal_year(np)
    prior_fy = cfy - 1
    has_prior = any(f['fiscal_year'] == prior_fy and
                    f['status'] in ('FILED', 'PUBLIC_DISCLOSED', 'SUPERSEDED')
                    for f in filings)
    if not has_prior and t > filing_due_date(np, prior_fy):
        return 'NON_COMPLIANT'
    dno_covering = [p for p in pols if p['policy_type'] == 'DNO' and
                    p['status'] == 'ACTIVE' and
                    p['policy_start_date'] <= t < p['policy_end_date']]
    if not dno_covering:
        return 'NON_COMPLIANT'

    # AT_RISK
    if any(r['status'] in ('RENEWAL_DUE', 'RENEWAL_SUBMITTED') for r in regs):
        return 'AT_RISK'
    if any(disclosure_overdue(f) for f in filings):
        return 'AT_RISK'
    for p in dno_covering:
        if p['policy_end_date'] <= t + timedelta(days=30):
            succ = any(q is not p and q['policy_type'] == 'DNO' and
                       q['status'] in ('BOUND', 'ACTIVE') and
                       q['policy_start_date'] <= p['policy_end_date']
                       for q in pols)
            if not succ:
                return 'AT_RISK'
    if t > fy_start_dt(np, cfy) + timedelta(days=90):
        for m in active_members(np_id):
            d = disclosure_for(m['id'], cfy)
            if d is None or d['status'] in ('FILED', 'UNDER_REVIEW'):
                return 'AT_RISK'
    return 'COMPLIANT'


# ---------------------------------------------------------------- cascades
def end_appointment(appt, reason):
    appt['status'] = 'ENDED'
    appt['ended_reason'] = reason
    touch(appt)
    committee = store.committees.get(appt['committee_id'])
    if committee is not None and committee['status'] == 'ACTIVE' and \
            committee_active_count(committee['id']) < committee['min_members']:
        committee['status'] = 'DORMANT'
        touch(committee)
        cancel_committee_meetings(committee['id'])


def cancel_committee_meetings(committee_id):
    for mt in store.meetings.values():
        if mt['committee_id'] == committee_id and mt['status'] == 'SCHEDULED':
            mt['status'] = 'CANCELLED'
            touch(mt)


def member_departure(member, new_status, reason):
    member['status'] = new_status
    touch(member)
    for term in list(store.terms.values()):
        if term['board_member_id'] == member['id'] and \
                term['status'] in ('SCHEDULED', 'ACTIVE'):
            term['status'] = 'VACATED'
            touch(term)
    for appt in list(store.appointments.values()):
        if appt['board_member_id'] == member['id'] and appt['status'] == 'ACTIVE':
            end_appointment(appt, reason)


def withdraw_inflight_fundraising(np_id):
    for mo in store.motions.values():
        if mo['nonprofit_id'] == np_id and mo['category'] == 'FUNDRAISING' and \
                mo['status'] in ('INTRODUCED', 'VOTING_OPEN', 'TABLED'):
            mo['status'] = 'WITHDRAWN'
            touch(mo)


# ---------------------------------------------------------------- sweep
def compliance_sweep(np):
    t = store.get_clock()
    np_id = np['id']
    np_terms = [x for x in store.terms.values() if x['nonprofit_id'] == np_id]
    for term in sorted(np_terms, key=lambda x: (x['start_date'], x['_seq'])):
        if term['status'] == 'SCHEDULED' and term['start_date'] <= t:
            term['status'] = 'ACTIVE'
            touch(term)
    for term in sorted(np_terms, key=lambda x: (x['start_date'], x['_seq'])):
        if term['status'] == 'ACTIVE' and t >= term['end_date']:
            term['status'] = 'COMPLETED'
            touch(term)
    for member in [m for m in store.members.values()
                   if m['nonprofit_id'] == np_id and m['status'] == 'ACTIVE']:
        m_terms = [x for x in np_terms
                   if x['board_member_id'] == member['id'] and x['status'] != 'VACATED']
        if not m_terms:
            continue
        latest = max(m_terms, key=lambda x: (x['start_date'], x['_seq']))
        if latest['status'] == 'COMPLETED':
            b = adopted_bylaws(np_id)
            chain_len = len(member_chain(member['id']))
            if b is not None and chain_len >= b['max_consecutive_terms']:
                member['status'] = 'TERM_LIMITED_OUT'
            else:
                member['status'] = 'PAST'
            touch(member)
    for reg in [r for r in store.registrations.values()
                if r['nonprofit_id'] == np_id]:
        end = reg['current_period_end']
        if reg['status'] in ('REGISTERED', 'RENEWAL_DUE', 'RENEWAL_SUBMITTED') \
                and t >= end:
            reg['status'] = 'LAPSED'
            touch(reg)
            withdraw_inflight_fundraising(np_id)
        elif reg['status'] == 'REGISTERED' and end - timedelta(days=60) <= t < end:
            reg['status'] = 'RENEWAL_DUE'
            touch(reg)
    for pol in [p for p in store.policies.values() if p['nonprofit_id'] == np_id]:
        if pol['status'] == 'ACTIVE' and t >= pol['policy_end_date']:
            pol['status'] = 'EXPIRED'
            touch(pol)


# ---------------------------------------------------------------- serializers
def ser_nonprofit(e):
    return {
        'id': e['id'], 'name': e['name'], 'ein': e['ein'],
        'state_of_incorporation': e['state_of_incorporation'],
        'fiscal_year_end_month': e['fiscal_year_end_month'],
        'annual_gross_receipts_cents': e['annual_gross_receipts_cents'],
        'current_fiscal_year': current_fiscal_year(e),
        'compliance_posture': compliance_posture(e),
        'adopted_policies': e['adopted_policies'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_bylaws(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'version_no': e['version_no'], 'quorum_pct': e['quorum_pct'],
        'quorum_basis': e['quorum_basis'],
        'amendment_threshold_pct': e['amendment_threshold_pct'],
        'term_length_years': e['term_length_years'],
        'max_consecutive_terms': e['max_consecutive_terms'],
        'term_cooloff_years': e['term_cooloff_years'],
        'board_size': e['board_size'], 'status': e['status'],
        'adopted_at': iso(e['adopted_at']) if e['adopted_at'] else None,
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_amendment(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'base_bylaws_id': e['base_bylaws_id'], 'title': e['title'],
        'proposed_fields': e['proposed_fields'], 'motion_id': e['motion_id'],
        'status': e['status'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_member(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'full_name': e['full_name'], 'email': e['email'],
        'skill_tags': e['skill_tags'], 'officer_role': e['officer_role'],
        'is_independent': e['is_independent'], 'status': e['status'],
        'consecutive_terms_served': len(member_chain(e['id'])),
        'has_active_restrictions': has_active_restrictions(e),
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_term(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'board_member_id': e['board_member_id'], 'bylaws_id': e['bylaws_id'],
        'start_date': iso(e['start_date']), 'end_date': iso(e['end_date']),
        'chain_index': chain_index_of(e), 'status': e['status'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_committee(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'], 'name': e['name'],
        'type': e['type'], 'min_members': e['min_members'],
        'authorized_size': e['authorized_size'],
        'requires_all_independent': e['requires_all_independent'],
        'active_member_count': committee_active_count(e['id']),
        'status': e['status'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_appointment(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'committee_id': e['committee_id'],
        'board_member_id': e['board_member_id'],
        'committee_role': e['committee_role'], 'status': e['status'],
        'ended_reason': e['ended_reason'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_meeting(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'committee_id': e['committee_id'],
        'scheduled_start': iso(e['scheduled_start']),
        'duration_minutes': e['duration_minutes'],
        'notice_sent_at': iso(e['notice_sent_at']) if e['notice_sent_at'] else None,
        'notice_waived': e['notice_waived'], 'status': e['status'],
        'attendance': e['attendance'], 'quorum_base': e['quorum_base'],
        'quorum_required': e['quorum_required'], 'quorum_met': e['quorum_met'],
        'minutes_text': e['minutes_text'],
        'minutes_recorded_by': e['minutes_recorded_by'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_motion(e):
    f, n, a, r = motion_tallies(e['id'])
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'meeting_id': e['meeting_id'],
        'bylaws_amendment_id': e['bylaws_amendment_id'],
        'policy_title': e['policy_title'], 'title': e['title'],
        'category': e['category'], 'threshold': e['threshold'],
        'threshold_basis': e['threshold_basis'],
        'votes_for': f, 'votes_against': n, 'votes_abstain': a,
        'votes_recused': r, 'required_votes': e['required_votes'],
        'status': e['status'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_vote(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'motion_id': e['motion_id'], 'board_member_id': e['board_member_id'],
        'choice': e['choice'], 'created_at': e['created_at'],
    }


def ser_disclosure(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'board_member_id': e['board_member_id'], 'fiscal_year': e['fiscal_year'],
        'answers': e['answers'], 'has_conflict': e['has_conflict'],
        'status': e['status'], 'reviewer_member_id': e['reviewer_member_id'],
        'restriction_categories': e['restriction_categories'],
        'filed_at': iso(e['filed_at']) if e['filed_at'] else None,
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_evaluation(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'fiscal_year': e['fiscal_year'], 'executive_name': e['executive_name'],
        'scores': e['scores'],
        'provisional_composite': e['provisional_composite'],
        'final_composite': e['final_composite'], 'rating': e['rating'],
        'recorded_by_user_id': e['recorded_by_user_id'],
        'ratified_by_user_id': e['ratified_by_user_id'], 'status': e['status'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_succession(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'target_role': e['target_role'], 'readiness': e['readiness'],
        'interim_designee_member_id': e['interim_designee_member_id'],
        'interim_designee_name': e['interim_designee_name'],
        'status': e['status'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_filing(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'fiscal_year': e['fiscal_year'],
        'supersedes_filing_id': e['supersedes_filing_id'],
        'total_revenue_cents': e['total_revenue_cents'],
        'total_expenses_cents': e['total_expenses_cents'],
        'contributions_cents': e['contributions_cents'],
        'program_service_revenue_cents': e['program_service_revenue_cents'],
        'net_change_cents': e['net_change_cents'],
        'public_support_ratio': float(e['public_support_ratio']),
        'preparer_user_id': e['preparer_user_id'],
        'approved_by_user_id': e['approved_by_user_id'],
        'reviewed_by_member_ids': e['reviewed_by_member_ids'],
        'review_required_count': e['review_required_count'],
        'filing_due_date': iso(e['filing_due_date']),
        'filed_on': iso(e['filed_on']) if e['filed_on'] else None,
        'filed_late': e['filed_late'],
        'public_disclosure_posted_at': iso(e['public_disclosure_posted_at'])
        if e['public_disclosure_posted_at'] else None,
        'disclosure_overdue': disclosure_overdue(e),
        'status': e['status'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_registration(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'state_code': e['state_code'],
        'renewal_cycle_months': e['renewal_cycle_months'],
        'current_period_end': iso(e['current_period_end']),
        'contributions_in_state_cents': e['contributions_in_state_cents'],
        'renewal_fee_cents': e['renewal_fee_cents'], 'status': e['status'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }


def ser_policy(e):
    return {
        'id': e['id'], 'nonprofit_id': e['nonprofit_id'],
        'prior_policy_id': e['prior_policy_id'],
        'policy_type': e['policy_type'], 'carrier': e['carrier'],
        'coverage_limit_cents': e['coverage_limit_cents'],
        'premium_cents': e['premium_cents'],
        'policy_start_date': iso(e['policy_start_date']),
        'policy_end_date': iso(e['policy_end_date']),
        'acknowledge_gap': e['acknowledge_gap'], 'gap_days': e['gap_days'],
        'status': e['status'],
        'created_at': e['created_at'], 'updated_at': e['updated_at'],
        'version': e['version'],
    }
