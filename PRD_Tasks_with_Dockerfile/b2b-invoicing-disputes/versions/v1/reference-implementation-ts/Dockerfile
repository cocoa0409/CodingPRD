FROM node:18-alpine

# Install build dependencies for native modules (better-sqlite3)
RUN apk add --no-cache python3 make g++

WORKDIR /app
COPY package*.json ./

# Install dependencies (will build native modules for Alpine)
RUN npm install

COPY . .
EXPOSE 3000
ENV HOST=0.0.0.0
CMD ["npm", "start"]
