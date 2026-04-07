import { AxiosResponse } from 'axios';
import { ApiResponse } from './types';
import { validateApiResponseStructure } from './validators';

export interface PaginationAssertOptions {
  expectedTotal: number;
  expectedHasMore?: boolean;
  elementAssertor?: (element: unknown) => void;
}

export function assertPaginatedList<T>(
  response: AxiosResponse<ApiResponse<T[]>>,
  options: PaginationAssertOptions
): void {
  const envelope = validateApiResponseStructure(response, { expectPaginated: true });
  const { limit, offset, total_count, has_more } = envelope.meta;
  const { data } = envelope;

  if (!Array.isArray(data)) {
    throw new Error('Paginated response data must be an array');
  }

  if (total_count !== options.expectedTotal) {
    throw new Error(
      `Expected total_count ${options.expectedTotal}, got ${total_count}`
    );
  }

  if (typeof limit === 'undefined') {
    throw new Error('meta.limit is required for paginated responses');
  }
  if (typeof offset === 'undefined') {
    throw new Error('meta.offset is required for paginated responses');
  }
  if (typeof total_count === 'undefined') {
    throw new Error('meta.total_count is required for paginated responses');
  }

  if (data.length > limit) {
    throw new Error(
      `Response contains ${data.length} items, exceeding limit ${limit}`
    );
  }

  const calculatedHasMore = offset + limit < total_count;
  if (has_more !== calculatedHasMore) {
    throw new Error(
      `has_more ${has_more} does not match calculation (offset ${offset} + limit ${limit} < total ${total_count})`
    );
  }

  if (options.expectedHasMore !== undefined && has_more !== options.expectedHasMore) {
    throw new Error(
      `Expected has_more to be ${options.expectedHasMore}, got ${has_more}`
    );
  }

  if (options.elementAssertor) {
    data.forEach((element, index) => {
      try {
        options.elementAssertor!(element);
      } catch (error) {
        throw new Error(
          `Element at index ${index} failed validation: ${(error as Error).message}`
        );
      }
    });
  }
}

export function validatePaginationParams(
  limit: unknown,
  offset: unknown
): void {
  if (limit !== undefined) {
    const limitNum = Number(limit);
    if (!Number.isInteger(limitNum) || limitNum < 1 || limitNum > 100) {
      throw new Error('limit must be integer between 1 and 100');
    }
  }

  if (offset !== undefined) {
    const offsetNum = Number(offset);
    if (!Number.isInteger(offsetNum) || offsetNum < 0) {
      throw new Error('offset must be non-negative integer');
    }
  }
}
