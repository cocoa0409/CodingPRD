"""Knowledge base articles (with revision chains) and article views."""
from flask import Blueprint

import db
from db import bump
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok_list, ok_object
from serializers import (article_view_count, ser_article, ser_article_view)
from validate import (enum_filter, get_body, opt_str, opt_str_list,
                      parse_pagination, req_str, str_filter, paginate, MISSING)

bp = Blueprint('kb', __name__)

ARTICLE_STATUSES = ('DRAFT', 'IN_REVIEW', 'PUBLISHED', 'SUPERSEDED', 'ARCHIVED')
_AUTHOR_ROLES = ('KnowledgeManager', 'HelpDeskAgent', 'SpecialistAgent')
_READ_ROLES = ('Employee', 'KnowledgeManager', 'HRServicesAdmin',
               'HelpDeskAgent', 'SpecialistAgent', 'SensitiveCaseManager')
_VIEW_LIST_ROLES = ('HRServicesAdmin', 'KnowledgeManager', 'HelpDeskAgent',
                    'SpecialistAgent', 'SensitiveCaseManager')
_VIEW_READ_ROLES = ('Employee',) + _VIEW_LIST_ROLES


@bp.post('/kb-articles')
def create_article():
    ctx = authenticate()
    require_roles(ctx, *_AUTHOR_ROLES)
    body = get_body()
    title = req_str(body, 'title')
    art_body = req_str(body, 'body')
    category_id = req_str(body, 'category_id')
    keywords = opt_str_list(body, 'keywords', default=[])
    supersedes_id = opt_str(body, 'supersedes_article_id')
    if category_id not in db.categories:
        raise ApiError('ERR_CATEGORY_NOT_FOUND', 404, 'category_id references no category')
    target = None
    if supersedes_id is not None:
        target = db.articles.get(supersedes_id)
        if target is None:
            raise ApiError('ERR_ARTICLE_NOT_FOUND', 404,
                           'supersedes_article_id references no article')
    # Referential usability: a revision target must be PUBLISHED at creation.
    if target is not None and target['status'] != 'PUBLISHED':
        raise ApiError('ERR_ARTICLE_INVALID_STATE', 409,
                       'a revision target must be PUBLISHED at creation')
    rec = {
        'title': title,
        'body': art_body,
        'keywords': keywords,
        'category_id': category_id,
        'author_user_id': ctx.user_id,
        'status': 'DRAFT',
        'supersedes_article_id': supersedes_id,
        'published_at': None,
        'published_by_user_id': None,
    }
    db.stamp_common(rec)
    db.articles[rec['id']] = rec
    return ok_object(ser_article(rec), status=201)


def _matches_q(a, q):
    needle = q.lower()
    if needle in a['title'].lower():
        return True
    return any(needle in k.lower() for k in a['keywords'])


@bp.get('/kb-articles')
def list_articles():
    ctx = authenticate()
    require_roles(ctx, *_READ_ROLES)
    q = str_filter('q')
    cat_f = str_filter('category_id')
    status_f = enum_filter('status', ARTICLE_STATUSES)
    supersedes_f = str_filter('supersedes_article_id')
    limit, offset = parse_pagination()
    rows = list(db.articles.values())
    if ctx.role == 'Employee':
        # Employees see PUBLISHED only.
        rows = [a for a in rows if a['status'] == 'PUBLISHED']
    if q is not MISSING:
        rows = [a for a in rows if _matches_q(a, q)]
    if cat_f is not MISSING:
        rows = [a for a in rows if a['category_id'] == cat_f]
    if status_f is not MISSING:
        rows = [a for a in rows if a['status'] == status_f]
    if supersedes_f is not MISSING:
        rows = [a for a in rows if a['supersedes_article_id'] == supersedes_f]
    # Search ordering exception: view_count DESC, created_at DESC.
    rows.sort(key=lambda a: (-article_view_count(a['id']),
                             -a['created_at'].timestamp(), -a['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_article(a) for a in page], limit, offset, total)


@bp.get('/kb-articles/<article_id>')
def get_article(article_id):
    ctx = authenticate()
    require_roles(ctx, *_READ_ROLES)
    a = db.articles.get(article_id)
    if a is None:
        raise ApiError('ERR_ARTICLE_NOT_FOUND', 404, 'no such article')
    if ctx.role == 'Employee' and a['status'] != 'PUBLISHED':
        # Indistinguishable from absence for employees.
        raise ApiError('ERR_ARTICLE_NOT_FOUND', 404, 'no such article')
    return ok_object(ser_article(a))


@bp.post('/kb-articles/<article_id>/submit-review')
def submit_review(article_id):
    ctx = authenticate()
    require_roles(ctx, *_AUTHOR_ROLES)
    a = db.articles.get(article_id)
    if a is None:
        raise ApiError('ERR_ARTICLE_NOT_FOUND', 404, 'no such article')
    # Author or any KnowledgeManager.
    if ctx.role != 'KnowledgeManager' and ctx.user_id != a['author_user_id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'only the author or a KnowledgeManager may submit for review')
    if a['status'] != 'DRAFT':
        raise ApiError('ERR_ARTICLE_INVALID_STATE', 409, 'article is not DRAFT')
    a['status'] = 'IN_REVIEW'
    bump(a)
    return ok_object(ser_article(a))


@bp.post('/kb-articles/<article_id>/publish')
def publish_article(article_id):
    ctx = authenticate()
    require_roles(ctx, 'KnowledgeManager')
    a = db.articles.get(article_id)
    if a is None:
        raise ApiError('ERR_ARTICLE_NOT_FOUND', 404, 'no such article')
    if a['status'] != 'IN_REVIEW':
        raise ApiError('ERR_ARTICLE_INVALID_STATE', 409, 'article is not IN_REVIEW')
    # Segregation of duties: author may not publish their own article.
    if ctx.user_id == a['author_user_id']:
        raise ApiError('ERR_AUTHOR_CANNOT_PUBLISH', 403,
                       'the author may not publish their own article')
    target = None
    if a['supersedes_article_id'] is not None:
        target = db.articles.get(a['supersedes_article_id'])
        if target is None or target['status'] != 'PUBLISHED':
            raise ApiError('ERR_ARTICLE_INVALID_STATE', 409,
                           'the revision chain head is no longer PUBLISHED')
    a['status'] = 'PUBLISHED'
    a['published_at'] = db.now()
    a['published_by_user_id'] = ctx.user_id
    bump(a)
    if target is not None:
        # Atomic supersede: exactly one PUBLISHED head per chain.
        target['status'] = 'SUPERSEDED'
        bump(target)
    return ok_object(ser_article(a))


@bp.post('/kb-articles/<article_id>/return-draft')
def return_draft(article_id):
    ctx = authenticate()
    require_roles(ctx, 'KnowledgeManager')
    a = db.articles.get(article_id)
    if a is None:
        raise ApiError('ERR_ARTICLE_NOT_FOUND', 404, 'no such article')
    if a['status'] != 'IN_REVIEW':
        raise ApiError('ERR_ARTICLE_INVALID_STATE', 409, 'article is not IN_REVIEW')
    a['status'] = 'DRAFT'
    bump(a)
    return ok_object(ser_article(a))


@bp.post('/kb-articles/<article_id>/archive')
def archive_article(article_id):
    ctx = authenticate()
    require_roles(ctx, 'KnowledgeManager')
    a = db.articles.get(article_id)
    if a is None:
        raise ApiError('ERR_ARTICLE_NOT_FOUND', 404, 'no such article')
    if a['status'] != 'PUBLISHED':
        raise ApiError('ERR_ARTICLE_INVALID_STATE', 409, 'article is not PUBLISHED')
    a['status'] = 'ARCHIVED'
    bump(a)
    return ok_object(ser_article(a))


# ---- Article views (deflection telemetry) ----

@bp.post('/article-views')
def create_article_view():
    ctx = authenticate()
    require_roles(ctx, 'Employee')
    body = get_body()
    article_id = req_str(body, 'article_id')
    a = db.articles.get(article_id)
    if a is None:
        raise ApiError('ERR_ARTICLE_NOT_FOUND', 404, 'article_id references no article')
    if a['status'] != 'PUBLISHED':
        raise ApiError('ERR_ARTICLE_INVALID_STATE', 409,
                       'viewed article must be PUBLISHED')
    rec = {
        'employee_id': ctx.user_id,
        'article_id': article_id,
        'viewed_at': db.now(),
        'deflection_outcome': 'NONE',
    }
    db.stamp_created(rec)  # append-only: id + created_at only
    db.article_views[rec['id']] = rec
    return ok_object(ser_article_view(rec), status=201)


@bp.get('/article-views')
def list_article_views():
    ctx = authenticate()
    require_roles(ctx, *_VIEW_LIST_ROLES)
    emp_f = str_filter('employee_id')
    art_f = str_filter('article_id')
    outcome_f = enum_filter('deflection_outcome', ('NONE', 'TICKET_CREATED'))
    limit, offset = parse_pagination()
    rows = list(db.article_views.values())
    if emp_f is not MISSING:
        rows = [v for v in rows if v['employee_id'] == emp_f]
    if art_f is not MISSING:
        rows = [v for v in rows if v['article_id'] == art_f]
    if outcome_f is not MISSING:
        rows = [v for v in rows if v['deflection_outcome'] == outcome_f]
    rows.sort(key=lambda v: (v['created_at'], v['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_article_view(v) for v in page], limit, offset, total)


@bp.get('/article-views/<view_id>')
def get_article_view(view_id):
    ctx = authenticate()
    require_roles(ctx, *_VIEW_READ_ROLES)
    v = db.article_views.get(view_id)
    if v is None:
        raise ApiError('ERR_ARTICLE_NOT_FOUND', 404, 'no such article view')
    if ctx.role == 'Employee' and ctx.user_id != v['employee_id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'employees may read only their own article views')
    return ok_object(ser_article_view(v))
